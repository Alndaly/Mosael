from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from app.domain.workflows import NODE_TYPES, validate_graph
from app.domain.workflows.templates import (
    ModelChoice,
    full_video_generation_graph,
    transcript_video_cleanup_graph,
)
from app.domain.workflows.normalization import canonicalize_data_bindings

REF_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def _references(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield from (match.group(1) for match in REF_RE.finditer(value))
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _references(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _references(nested)


def _invalid_references(
    graph: dict[str, Any],
    *,
    virtual_roots: set[str] | None = None,
) -> list[str]:
    virtual_roots = virtual_roots or set()
    nodes = {node["id"]: node for node in graph["nodes"]}
    invalid: list[str] = []
    for node in graph["nodes"]:
        config = node.get("config") or {}
        for key, value in config.items():
            if node["type"] in {"loop_foreach", "loop_while", "subgraph"} and key in {
                "body",
                "output",
                "condition",
            }:
                continue
            for reference in _references(value):
                parts = reference.split(".")
                root = parts[0]
                if root in virtual_roots:
                    continue
                source = nodes.get(root)
                if source is None:
                    invalid.append(reference)
                    continue
                if len(parts) < 2:
                    continue
                outputs = NODE_TYPES[source["type"]].get("outputs") or []
                if "*params" not in outputs and parts[1] not in outputs:
                    invalid.append(reference)
    return invalid


def test_full_video_template_has_valid_refs_and_parallel_planning() -> None:
    graph = full_video_generation_graph(
        chat=ModelChoice(profile_id="chat-profile", provider="openai", model="chat-model"),
        video=ModelChoice(profile_id="video-profile", provider="fal", model="video-model"),
    )

    assert validate_graph(graph) == []
    assert _invalid_references(graph) == []
    assert graph["meta"] == {
        "template_id": "full_video_generation",
        "template_version": 3,
        "source": "official",
    }

    successors: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        successors.setdefault(edge["source"], set()).add(edge["target"])
    assert successors["creative_brief"] == {"narrative_script", "visual_bible", "video_project"}
    assert successors["export_final"] == {"done_notice", "output"}

    loop = next(node for node in graph["nodes"] if node["id"] == "generate_and_assemble")
    body = loop["config"]["body"]
    assert validate_graph(body, require_start=False) == []
    assert _invalid_references(body, virtual_roots={"loop", "input"}) == []
    body_ids = {node["id"] for node in body["nodes"]}
    assert {reference.split(".")[0] for reference in _references(loop["config"]["output"])} <= body_ids
    organize = next(node for node in body["nodes"] if node["id"] == "organize_clip")
    assert organize["inputs"] == ["asset_ids"]
    assert any(
        edge.get("kind") == "data"
        and edge.get("source") == "generate_clip"
        and edge.get("source_output") == "asset_id"
        and edge.get("target") == "organize_clip"
        and edge.get("target_input") == "asset_ids"
        for edge in body["edges"]
    )


def test_transcript_cleanup_template_has_valid_refs_and_provenance() -> None:
    graph = transcript_video_cleanup_graph(
        chat=ModelChoice(profile_id="chat-profile", provider="openai", model="chat-model"),
    )

    # The source asset is intentionally selected by the user after installing the template.
    assert validate_graph(graph, require_config=False) == []
    assert _invalid_references(graph) == []
    assert graph["meta"] == {
        "template_id": "transcript_video_cleanup",
        "template_version": 2,
        "source": "official",
    }

    transcript = next(node for node in graph["nodes"] if node["id"] == "verbatim_transcript")
    assert transcript["config"]["asset_id"] == ""
    assert "asset_id" in transcript["inputs"]
    binding = next(
        edge
        for edge in graph["edges"]
        if edge.get("target") == "verbatim_transcript" and edge.get("target_input") == "asset_id"
    )
    assert {key: binding[key] for key in ("source", "source_output", "target", "target_input", "kind")} == {
        "source": "source_video",
        "source_output": "asset_id",
        "target": "verbatim_transcript",
        "target_input": "asset_id",
        "kind": "data",
    }
    assert not any(
        edge["source"] == "source_video"
        and edge["target"] == "verbatim_transcript"
        and edge.get("kind", "control") == "control"
        for edge in graph["edges"]
    )


def test_data_binding_normalization_is_lossless_and_idempotent() -> None:
    legacy = {
        "nodes": [
            {"id": "source", "type": "asset", "config": {"asset_id": "asset-1"}},
            {
                "id": "transcript",
                "type": "transcribe_asset",
                "config": {"asset_id": "{{ source.asset_id }}", "engine": "auto"},
            },
            {
                "id": "notice",
                "type": "notify",
                "config": {"title": "完成", "body": "已处理 {{source.name}}"},
            },
        ],
        "edges": [
            {"id": "source_transcript", "source": "source", "target": "transcript"},
            {"id": "transcript_notice", "source": "transcript", "target": "notice"},
        ],
    }

    normalized = canonicalize_data_bindings(legacy, node_types=NODE_TYPES)

    assert legacy["nodes"][1]["config"]["asset_id"] == "{{ source.asset_id }}"
    assert normalized["nodes"][1]["config"]["asset_id"] == ""
    assert normalized["nodes"][1]["inputs"] == ["asset_id"]
    assert normalized["nodes"][2]["config"]["body"] == "已处理 {{source.name}}"
    assert not any(edge["id"] == "source_transcript" for edge in normalized["edges"])
    assert canonicalize_data_bindings(normalized, node_types=NODE_TYPES) == normalized
