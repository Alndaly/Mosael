from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from app.domain.workflows import NODE_TYPES, validate_graph
from app.domain.workflows.templates import (
    ModelChoice,
    full_video_generation_graph,
    translated_dub_graph,
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
        "template_version": 5,
        "source": "official",
    }

    successors: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        successors.setdefault(edge["source"], set()).add(edge["target"])
    assert successors["creative_brief"] == {"narrative_script", "visual_bible", "video_project"}
    assert successors["export_final"] == {"done_notice", "output"}

    generate = next(node for node in graph["nodes"] if node["id"] == "generate_shots")
    assemble = next(node for node in graph["nodes"] if node["id"] == "assemble_timeline")
    for loop in (generate, assemble):
        body = loop["config"]["body"]
        assert validate_graph(body, require_start=False) == []
        assert _invalid_references(body, virtual_roots={"loop", "input"}) == []
    #: 生成可以同时跑(视频生成是整条流程最慢的一步);上时间线必须一镜接一镜。
    assert generate["config"]["concurrency"] == 3
    assert assemble["config"]["concurrency"] == 1
    assert successors["generate_shots"] == {"assemble_timeline"}
    assert successors["assemble_timeline"] == {"narration_subtitles"}
    assert successors["narration_subtitles"] == {"export_final"}
    organize = next(node for node in generate["config"]["body"]["nodes"] if node["id"] == "organize_clip")
    assert organize["inputs"] == ["asset_ids"]
    assert any(
        edge.get("kind") == "data"
        and edge.get("source") == "generate_clip"
        and edge.get("source_output") == "asset_id"
        and edge.get("target") == "organize_clip"
        and edge.get("target_input") == "asset_ids"
        for edge in generate["config"]["body"]["edges"]
    )
    subtitles = next(node for node in graph["nodes"] if node["id"] == "narration_subtitles")
    #: 整片没有口播时交出 0 条,不让一条已经生成完的片子在导出前失败。
    assert subtitles["config"]["allow_empty"] == "yes"
    assert subtitles["config"]["text_field"] == "caption.text"


def test_transcript_cleanup_template_has_valid_refs_and_provenance() -> None:
    graph = transcript_video_cleanup_graph(
        chat=ModelChoice(profile_id="chat-profile", provider="openai", model="chat-model"),
    )

    # The source asset is intentionally selected by the user after installing the template.
    assert validate_graph(graph, require_config=False) == []
    assert _invalid_references(graph) == []
    assert graph["meta"] == {
        "template_id": "transcript_video_cleanup",
        "template_version": 4,
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
    #: 转写读的是**降噪后**的那份 —— 底噪会让转写认错字,而整理方案是照着逐字稿切的。
    assert {key: binding[key] for key in ("source", "source_output", "target", "target_input", "kind")} == {
        "source": "clean_audio",
        "source_output": "asset_id",
        "target": "verbatim_transcript",
        "target_input": "asset_id",
        "kind": "data",
    }
    clean = next(node for node in graph["nodes"] if node["id"] == "clean_audio")
    assert clean["type"] == "denoise_audio"
    #: 官方模板用内置引擎:不用装、不动背景音乐。
    assert clean["config"]["engine"] == "auto"
    on_timeline = next(edge for edge in graph["edges"]
                       if edge.get("target") == "source_on_timeline" and edge.get("target_input") == "asset_id")
    assert on_timeline["source"] == "clean_audio", "放上时间线的也该是降噪后的那份"
    assert not any(
        edge["source"] == "source_video"
        and edge["target"] == "verbatim_transcript"
        for edge in graph["edges"]
    )
    cleanup_plan = next(node for node in graph["nodes"] if node["id"] == "cleanup_plan")
    assert "token_columns" in cleanup_plan["config"]["prompt"]


def test_full_video_narration_lands_on_its_own_shot() -> None:
    """口播放在这一镜画面开始的那一秒,而不是接在上一段口播后面。

    此前是后者:口播长短不一,第 n 段落在前 n−1 段口播时长之和上,越往后和画面错得越多。
    (实际跑一遍的验证见 test_loop_concurrency_and_full_video_assembly。)
    """
    graph = full_video_generation_graph(
        chat=ModelChoice(profile_id="chat-profile", provider="openai", model="chat-model"),
        video=ModelChoice(profile_id="video-profile", provider="fal", model="video-model"),
    )
    assemble = next(node for node in graph["nodes"] if node["id"] == "assemble_timeline")
    body = assemble["config"]["body"]
    narration = next(node for node in body["nodes"] if node["id"] == "append_narration")
    clip = next(node for node in body["nodes"] if node["id"] == "append_clip")
    at = next(edge for edge in body["edges"] if edge.get("target") == "append_narration" and edge.get("target_input") == "at")
    assert (at["source"], at["source_output"]) == ("append_clip", "timeline_start")
    #: 比镜头长就压进去(兜底);镜头多长就是画面片段截的那一段。
    assert narration["config"]["max_duration"] == clip["config"]["end"]
    storyboard = next(node for node in graph["nodes"] if node["id"] == "storyboard")
    assert "每秒约 4 字" in storyboard["config"]["system"]


def test_translated_dub_notice_says_what_happened_to_the_original_audio() -> None:
    """成功通知引用实际处理方式；分离不可用时任务会在到达通知节点前失败。"""
    graph = translated_dub_graph()
    notice = next(node for node in graph["nodes"] if node["id"] == "done_notice")
    references = json.dumps(notice, ensure_ascii=False) + json.dumps(graph["edges"], ensure_ascii=False)
    assert "original_audio_note" in references
    assert graph["meta"]["template_version"] == 2


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
        # db=None = 纯静态上下文:不点名连接,只看内置目录。
        assert not _supports_text_to_video(None, ModelChoice(provider="alibaba", model="wan2.7-i2v"))
        assert _supports_text_to_video(None, ModelChoice(provider="minimax", model="MiniMax-H3"))

    def test_认不出来的模型算能(self) -> None:
        """用户自建的、ComfyUI 的工作流查不到能力表。落到"不认识"时拿窄名单去拦,
        会把本来能用的模型挡在外面 —— 见 known_capabilities_for 的说明。"""
        from app.domain.workflows.templates import _supports_text_to_video

        assert _supports_text_to_video(None, ModelChoice(provider="self-hosted", model="my-own-t2v"))
        # 但"根本没有模型"不算能:那是空,不是未知。
        assert not _supports_text_to_video(None, ModelChoice())

    def test_生成节点不喂首帧所以不能用图生视频(self) -> None:
        """把节点实际的输入摆出来:它只有 prompt / negative_prompt / parameters,
        没有任何首帧字段。这条测试在有人给 generate_clip 加首帧时会失败 —— 那时候
        上面挑模型的规矩就该跟着改,而不是让两边悄悄对不上。"""
        graph = full_video_generation_graph(
            chat=ModelChoice(provider="p", model="c"),
            video=ModelChoice(provider="minimax", model="MiniMax-H3"),
        )
        # 它在「各镜同时生成」那个循环的 body 里,不是顶层节点。
        loop = next(n for n in graph["nodes"] if n["id"] == "generate_shots")
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

    def _loops(self, voice_id: str = "v1") -> tuple[dict[str, Any], dict[str, Any]]:
        """(各镜同时生成, 按镜头顺序接上时间线) 两个循环的 config。"""
        graph = full_video_generation_graph(
            chat=ModelChoice(provider="p", model="c"),
            video=ModelChoice(provider="minimax", model="MiniMax-H3"),
            voice_id=voice_id,
        )
        by_id = {n["id"]: n for n in graph["nodes"]}
        return by_id["generate_shots"]["config"], by_id["assemble_timeline"]["config"]

    def test_口播被合成并接进音轨(self) -> None:
        generate, assemble = self._loops()
        made = {n["id"]: n for n in generate["body"]["nodes"]}
        placed = {n["id"]: n for n in assemble["body"]["nodes"]}

        assert made["narrate"]["type"] == "synthesize_speech"
        assert made["narrate"]["config"]["text"] == "{{loop.item.narration}}"
        # 接的是**音轨**,不是画面那条 —— 接错轨道的话口播会把画面顶掉。
        assert placed["append_narration"]["config"]["track_id"] == "{{input.audio_track_id}}"
        assert assemble["inputs"]["audio_track_id"] == "{{video_project.audio_track_id}}"
        # 上时间线那一轮遍历的是生成那一轮的结果:口播素材就是那一项里 narrate 的产物。
        assert placed["append_narration"]["config"]["asset_id"] == "{{loop.item.narrate.asset_id}}"

    def test_口播不按镜头定长裁(self) -> None:
        """画面每镜定长,口播不是。硬裁到 clip_seconds 会把话切掉半句 —— 太长就加速,不裁。"""
        _, assemble = self._loops()
        nodes = {n["id"]: n for n in assemble["body"]["nodes"]}
        assert "end" not in nodes["append_narration"]["config"]
        assert nodes["append_narration"]["config"]["max_duration"]

    def test_没选音色时整段跳过而不是失败(self) -> None:
        """voice_id 是 synthesize_speech 的必填项,模板不可能替用户猜一个。空着要得到
        一部默片,而不是一个跑到第一镜就失败的工作流。"""
        generate, assemble = self._loops(voice_id="")
        nodes = {n["id"]: n for n in generate["body"]["nodes"]}
        gate = nodes["has_voice"]
        assert gate["type"] == "condition"
        assert gate["config"] == {"left": "{{input.voice_id}}", "op": "not_empty"}
        # 合成只挂在 true 分支上。
        to_narration = [e for e in generate["body"]["edges"] if e["source"] == "has_voice"]
        assert to_narration and all(e.get("branch") == "true" for e in to_narration)
        # 上时间线那一轮:没合成出口播的镜头不去接口播。
        placed = {n["id"]: n for n in assemble["body"]["nodes"]}
        assert placed["has_audio"]["config"] == {"left": "{{loop.item.narrate.asset_id}}", "op": "not_empty"}
        gated = [e for e in assemble["body"]["edges"] if e["source"] == "has_audio"]
        assert gated and all(e.get("branch") == "true" for e in gated)

    def test_这一镜没口播也跳过(self) -> None:
        """分镜 schema 明说"无则写空字符串" —— 纯画面镜头是正常的,而空文本交给合成会失败,
        那一镜失败会拖垮整轮循环。"""
        generate, _ = self._loops()
        nodes = {n["id"]: n for n in generate["body"]["nodes"]}
        assert nodes["has_narration"]["config"] == {"left": "{{loop.item.narration}}", "op": "not_empty"}
        edges = [e for e in generate["body"]["edges"] if e["source"] == "has_narration"]
        assert edges and all(e.get("branch") == "true" for e in edges)

    def test_口播链路不影响画面(self) -> None:
        """加配音不该动到已经能用的那半边。"""
        generate, assemble = self._loops()
        placed = {n["id"]: n for n in assemble["body"]["nodes"]}
        assert placed["append_clip"]["config"]["track_id"] == "{{input.video_track_id}}"
        assert placed["append_clip"]["config"]["asset_id"] == "{{loop.item.generate_clip.asset_id}}"
        # 画面和口播在生成那一轮里是两条互不依赖的支路 —— 口播失败不会拖住画面的顺序。
        roots = {n["id"] for n in generate["body"]["nodes"]} - {e["target"] for e in generate["body"]["edges"]}
        assert {"generate_clip", "has_voice"} <= roots


def test_模板里的节点名跟着界面语言走() -> None:
    """图一落库就是用户的数据(他随时能改名),所以语言在**造图那一刻**定,不在出口翻。

    此前这些名字是写死的中文:英文用户从模板建一条流程,画布上一排中文节点。
    """
    from app.core.db import SessionLocal
    from app.domain.workflows.templates import (
        FULL_VIDEO_GENERATION,
        TRANSCRIPT_VIDEO_CLEANUP,
        TRANSLATED_DUB,
        built_in_template_graph,
    )
    from tests.util import fresh_client

    fresh_client()
    with SessionLocal() as db:
        for template_id in (FULL_VIDEO_GENERATION, TRANSCRIPT_VIDEO_CLEANUP, TRANSLATED_DUB):
            for locale in ("zh", "en"):
                graph = built_in_template_graph(db, template_id, user_id="", workspace_id="", locale=locale)
                names = _names(graph)
                assert names, template_id
                assert all(isinstance(name, str) and name.strip() for name in names), f"{template_id} 有节点没名字"
                chinese = [name for name in names if any("一" <= ch <= "鿿" for ch in name)]
                if locale == "en":
                    assert not chinese, f"{template_id} 的英文图里还有中文节点名:{chinese}"
                else:
                    assert chinese, f"{template_id} 的中文图怎么一个中文名都没有"


def _names(graph: dict) -> list:
    out = []
    for node in graph.get("nodes") or []:
        out.append(node.get("name"))
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict):
            out.extend(_names(body))
    return out


def test_每个模板节点都写了中英两份名字() -> None:
    """棘轮:名字是**贴着节点写的**语言对象(和插件清单同一套),漏一种语言就少一半界面。"""
    import ast
    import pathlib

    source = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows" / "templates.py"
    missing = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        if not {"id", "type", "name"} <= set(keys):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and key.value == "name"):
                continue
            if isinstance(value, ast.Constant):
                missing.append(f"第 {value.lineno} 行:{value.value}(只有一种语言)")
            elif isinstance(value, ast.Dict):
                langs = {k.value for k in value.keys if isinstance(k, ast.Constant)}
                if not {"zh", "en"} <= langs:
                    missing.append(f"第 {value.lineno} 行:少了 {sorted({'zh', 'en'} - langs)}")
    assert not missing, "\n".join(missing)
