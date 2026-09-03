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
        "template_version": 2,
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


def test_transcript_cleanup_template_has_valid_refs_and_provenance() -> None:
    graph = transcript_video_cleanup_graph(
        chat=ModelChoice(profile_id="chat-profile", provider="openai", model="chat-model"),
    )

    # The source asset is intentionally selected by the user after installing the template.
    assert validate_graph(graph, require_config=False) == []
    assert _invalid_references(graph) == []
    assert graph["meta"] == {
        "template_id": "transcript_video_cleanup",
        "template_version": 1,
        "source": "official",
    }
