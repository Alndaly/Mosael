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
        "template_version": 3,
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
    cleanup_plan = next(node for node in graph["nodes"] if node["id"] == "cleanup_plan")
    assert "token_columns" in cleanup_plan["config"]["prompt"]


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


class Test示范工作流要挑得动的模型:
    """`generate_clip` **只给一段提示词**,所以模型必须能纯文生视频。

    内置目录里有十几个只声明 image-to-video 的视频模型(seedance-*-image-to-video、
    wan2.7-i2v 等)。用户的 video 默认模型恰好是其中之一时,示范工作流从第一次运行起就是
    坏的 —— 而报错发生在跑到那一步之后,离"我只是打开了示范模板"已经很远,没人会往
    "模板挑错了模型"上想。
    """

    def test_只会图生视频的模型不该被选中(self) -> None:
        from app.domain.workflows.templates import _supports_text_to_video

        # 内置目录里真实存在的两类,直接拿它们断言 —— 编一个假模型名会落进"不认识"那条路。
        assert not _supports_text_to_video(ModelChoice(provider="alibaba", model="wan2.7-i2v"))
        assert _supports_text_to_video(ModelChoice(provider="minimax", model="MiniMax-H3"))

    def test_认不出来的模型算能(self) -> None:
        """用户自建的、ComfyUI 的工作流查不到能力表。落到"不认识"时拿窄名单去拦,
        会把本来能用的模型挡在外面 —— 见 known_capabilities_for 的说明。"""
        from app.domain.workflows.templates import _supports_text_to_video

        assert _supports_text_to_video(ModelChoice(provider="self-hosted", model="my-own-t2v"))
        # 但"根本没有模型"不算能:那是空,不是未知。
        assert not _supports_text_to_video(ModelChoice())

    def test_生成节点不喂首帧所以不能用图生视频(self) -> None:
        """把节点实际的输入摆出来:它只有 prompt / negative_prompt / parameters,
        没有任何首帧字段。这条测试在有人给 generate_clip 加首帧时会失败 —— 那时候
        上面挑模型的规矩就该跟着改,而不是让两边悄悄对不上。"""
        graph = full_video_generation_graph(
            chat=ModelChoice(provider="p", model="c"),
            video=ModelChoice(provider="minimax", model="MiniMax-H3"),
        )
        # 它在 loop_foreach 的 body 里,不是顶层节点。
        loop = next(n for n in graph["nodes"] if n["id"] == "generate_and_assemble")
        node = next(n for n in loop["config"]["body"]["nodes"] if n["id"] == "generate_clip")
        config = node["config"]
        assert config["prompt"]
        assert not any(key in config for key in ("first_frame", "image", "asset_id", "first_frame_url"))


class Test挑模型走真实的库:
    """上面几条验的是判断规则,这一条验的是**选择**:默认模型只会图生视频时,
    真的会绕开它去挑另一个。规则对而选择错,症状和完全没修一模一样。"""

    def _model(self, db, owner: str, vendor: str, model_id: str):
        from app.db.models import ProviderModel, ProviderProfile

        profile = ProviderProfile(owner_user_id=owner, vendor=vendor, name=vendor, enabled=True)
        db.add(profile)
        db.flush()
        row = ProviderModel(
            provider_profile_id=profile.id, model_id=model_id, enabled=True, capability_ids=["video"]
        )
        db.add(row)
        db.flush()
        return row

    def test_默认是图生视频时换一个能文生视频的(self) -> None:
        from app.core.db import SessionLocal
        from app.domain.provider_defaults import set_default
        from app.domain.workflows.templates import _text_to_video_model
        from tests.util import fresh_client

        fresh_client()
        user_id = "u1"
        with SessionLocal() as db:
            # 用户把默认设成了只会图生视频的那个。
            i2v = self._model(db, user_id, "alibaba", "wan2.7-i2v")
            t2v = self._model(db, user_id, "minimax", "MiniMax-H3")
            set_default(db, "video", i2v, owner_user_id=user_id)
            db.commit()

            picked = _text_to_video_model(db, user_id)
            assert picked.model == t2v.model_id, "只会图生视频的默认模型必须被绕开"

    def test_一个能文生视频的都没有就留空(self) -> None:
        """留空好过塞一个必然失败的进去:节点上的模型格空着,界面会让他去选。"""
        from app.core.db import SessionLocal
        from app.domain.workflows.templates import _text_to_video_model
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            self._model(db, "u1", "alibaba", "wan2.7-i2v")
            db.commit()
            assert _text_to_video_model(db, "u1").model == ""


class Test分镜写了口播就要真的配上:
    """分镜的 schema 给每镜留了 narration,创意简报、脚本、分镜三步都在为它服务 ——
    而此前**没有任何一个节点用它**,成片是默哑的。写了却不用,比不写更容易让人以为是坏了。
    """

    def _body(self, voice_id: str = "v1") -> dict[str, Any]:
        graph = full_video_generation_graph(
            chat=ModelChoice(provider="p", model="c"),
            video=ModelChoice(provider="minimax", model="MiniMax-H3"),
            voice_id=voice_id,
        )
        loop = next(n for n in graph["nodes"] if n["id"] == "generate_and_assemble")
        return graph, loop["config"]

    def test_口播被合成并接进音轨(self) -> None:
        _, loop = self._body()
        nodes = {n["id"]: n for n in loop["body"]["nodes"]}

        assert nodes["narrate"]["type"] == "synthesize_speech"
        assert nodes["narrate"]["config"]["text"] == "{{loop.item.narration}}"
        # 接的是**音轨**,不是画面那条 —— 接错轨道的话口播会把画面顶掉。
        assert nodes["append_narration"]["config"]["track_id"] == "{{input.audio_track_id}}"
        assert loop["inputs"]["audio_track_id"] == "{{video_project.audio_track_id}}"
        # 指向别的节点的引用会被规范化成一条**有类型的数据边**,配置里留空
        # (见 normalization.canonicalize_data_bindings)—— 所以断言那条边,不是那个字符串。
        assert any(
            e.get("kind") == "data"
            and e["source"] == "narrate"
            and e["target"] == "append_narration"
            and e.get("source_output") == "asset_id"
            and e.get("target_input") == "asset_id"
            for e in loop["body"]["edges"]
        )

    def test_口播不按镜头定长裁(self) -> None:
        """画面每镜定长,口播不是。硬裁到 clip_seconds 会把话切掉半句。"""
        _, loop = self._body()
        nodes = {n["id"]: n for n in loop["body"]["nodes"]}
        assert "end" not in nodes["append_narration"]["config"]

    def test_没选音色时整段跳过而不是失败(self) -> None:
        """voice_id 是 synthesize_speech 的必填项,模板不可能替用户猜一个。空着要得到
        一部默片,而不是一个跑到第一镜就失败的工作流。"""
        _, loop = self._body(voice_id="")
        nodes = {n["id"]: n for n in loop["body"]["nodes"]}
        gate = nodes["has_voice"]
        assert gate["type"] == "condition"
        assert gate["config"] == {"left": "{{input.voice_id}}", "op": "not_empty"}
        # 合成只挂在 true 分支上。
        to_narration = [e for e in loop["body"]["edges"] if e["source"] == "has_voice"]
        assert all(e.get("branch") == "true" for e in to_narration)

    def test_这一镜没口播也跳过(self) -> None:
        """分镜 schema 明说"无则写空字符串" —— 纯画面镜头是正常的,而空文本交给合成会失败,
        那一镜失败会拖垮整轮循环。"""
        _, loop = self._body()
        nodes = {n["id"]: n for n in loop["body"]["nodes"]}
        assert nodes["has_narration"]["config"] == {"left": "{{loop.item.narration}}", "op": "not_empty"}
        edges = [e for e in loop["body"]["edges"] if e["source"] == "has_narration"]
        assert all(e.get("branch") == "true" for e in edges)

    def test_口播链路不影响画面(self) -> None:
        """加配音不该动到已经能用的那半边。"""
        _, loop = self._body()
        nodes = {n["id"]: n for n in loop["body"]["nodes"]}
        assert nodes["append_clip"]["config"]["track_id"] == "{{input.video_track_id}}"
        assert loop["output"] == "{{generate_clip.asset_id}}"
