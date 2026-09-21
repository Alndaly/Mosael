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


SEEDANCE = ModelChoice(profile_id="video-profile", provider="bytedance", model="doubao-seedance-2-0-260128")
SEEDREAM = ModelChoice(profile_id="image-profile", provider="bytedance", model="doubao-seedream-4-0-250828")
CHAT = ModelChoice(profile_id="chat-profile", provider="openai", model="chat-model")


def _full_video(**overrides) -> dict[str, Any]:
    return full_video_generation_graph(**{"chat": CHAT, "image": SEEDREAM, "video": SEEDANCE, **overrides})


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(node for node in graph["nodes"] if node["id"] == node_id)


def test_full_video_template_has_valid_refs_and_parallel_planning() -> None:
    graph = _full_video()

    assert validate_graph(graph) == []
    assert _invalid_references(graph) == []
    assert graph["meta"] == {
        "template_id": "full_video_generation",
        "template_version": 7,
        "source": "official",
    }

    successors: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        successors.setdefault(edge["source"], set()).add(edge["target"])
    assert successors["creative_brief"] == {"narrative_script", "visual_bible", "video_project"}
    #: 角色三视图、场景设定图和分镜都从视觉圣经出发,三视图与设定图并行画。
    assert successors["visual_bible"] == {"character_sheets", "location_art", "storyboard"}
    assert successors["storyboard"] == {"set_design"}
    assert successors["set_design"] == {"build_set"}
    assert successors["export_final"] == {"done_notice", "output"}

    for loop_id in ("character_sheets", "location_art", "generate_shots", "assemble_timeline"):
        body = _node(graph, loop_id)["config"]["body"]
        assert validate_graph(body, require_start=False) == []
        assert _invalid_references(body, virtual_roots={"loop", "input"}) == []
    generate, assemble = _node(graph, "generate_shots"), _node(graph, "assemble_timeline")
    #: 生成可以同时跑(视频生成是整条流程最慢的一步);上时间线必须一镜接一镜。
    assert generate["config"]["concurrency"] == 3
    assert assemble["config"]["concurrency"] == 1
    assert successors["generate_shots"] == {"assemble_timeline"}
    assert successors["assemble_timeline"] == {"narration_subtitles"}
    assert successors["narration_subtitles"] == {"export_final"}
    organize = next(node for node in generate["config"]["body"]["nodes"] if node["id"] == "organize_clip")
    assert organize["inputs"] == ["asset_ids"]
    subtitles = _node(graph, "narration_subtitles")
    #: 整片没有口播时交出 0 条,不让一条已经生成完的片子在导出前失败。
    assert subtitles["config"]["allow_empty"] == "yes"
    assert subtitles["config"]["text_field"] == "caption.text"


class Test每一镜都有实物参考:
    """此前每一镜只有一段文字提示词:构图、机位、人物长相全靠视频模型猜,几镜之间谁也对不上谁。"""

    def _body(self, **overrides) -> dict[str, dict[str, Any]]:
        return {n["id"]: n for n in _node(_full_video(**overrides), "generate_shots")["config"]["body"]["nodes"]}

    def test_每镜先渲白模_视频挂在白模之后(self) -> None:
        body = self._body()
        assert body["render_blockout"]["type"] == "scene_render"
        assert body["render_blockout"]["config"]["shot_id"] == "shot-{{loop.item.shot_number}}"
        assert "{{render_blockout.camera_move}}" in body["generate_clip"]["config"]["prompt"], "镜头语言从机位轨迹算,进提示词"

    def test_两组素材都接上_由分镜逐镜选一组(self) -> None:
        clip = self._body()["generate_clip"]["config"]
        assert clip["source_group"] == "{{loop.item.reference_mode}}"
        roles = {line.rsplit(":", 1)[1] for line in clip["source_assets"] if ":" in line}
        assert {"first_frame", "last_frame", "reference_image", "reference_video"} <= roles
        assert "{{input.sheets}}" in clip["source_assets"], "全部角色的三视图整组接进来"

    def test_首帧按白模机位画_带着三视图和设定图(self) -> None:
        first = self._body()["paint_first_frame"]["config"]
        assert first["kind"] == "image" and first["model"] == SEEDREAM.model
        assert first["source_assets"][0] == "{{render_blockout.first_frame_asset_id}}:reference_image"
        assert {"{{input.sheets}}", "{{input.locations}}"} <= set(first["source_assets"])

    def test_尾帧接着首帧画(self) -> None:
        last = self._body()["paint_last_frame"]["config"]
        assert "{{paint_first_frame.asset_id}}:reference_image" in last["source_assets"]

    def test_角色三视图按角色逐个画_交出整组参考行(self) -> None:
        sheets = _node(_full_video(), "character_sheets")["config"]
        assert sheets["items"] == "{{visual_bible.json.characters}}"
        assert sheets["output"] == "{{sheet.asset_id}}:reference_image"

    def test_布景直接建成_3D_场景(self) -> None:
        build = _node(_full_video(), "build_set")
        assert build["type"] == "scene_create"
        assert _node(_full_video(), "set_design")["config"]["json_schema_name"] == "blockout_scene"


class Test分镜能选的路跟着视频模型走:
    """Seedance 上首尾帧组和参考素材组互斥;不同模型收的参考也不同 —— 分镜只能在模型真收的里面选。"""

    def _shot(self, video: ModelChoice) -> dict[str, Any]:
        storyboard = _node(_full_video(video=video), "storyboard")
        return storyboard["config"]["json_schema"]["properties"]["shots"]["items"]["properties"]

    def test_两种都收的模型两条路都能选_还能给尾帧(self) -> None:
        shot = self._shot(SEEDANCE)
        assert shot["reference_mode"]["enum"] == ["keyframes", "references"]
        assert "last_frame_prompt" in shot

    def test_认不出的模型只走首帧(self) -> None:
        """不猜它收参考素材 —— 首帧生视频是最通用的那条。"""
        shot = self._shot(ModelChoice(provider="self-hosted", model="my-own-i2v"))
        assert shot["reference_mode"]["enum"] == ["keyframes"]
        assert "last_frame_prompt" not in shot


def test_布景的形状就是_3D_场景的数据格式() -> None:
    """布景 LLM 的输出直接交给 scene_create 按 SceneContent 校验 —— 两边的字段必须对得上。"""
    from app.domain.scene_types import SceneContent, SceneObject, SceneShot
    from app.domain.workflows.templates import _set_design_schema

    schema = _set_design_schema()
    assert set(schema["properties"]) <= set(SceneContent.model_fields)
    obj = schema["properties"]["objects"]["items"]["properties"]
    assert set(obj) <= set(SceneObject.model_fields)
    assert set(schema["properties"]["shots"]["items"]["properties"]) <= set(SceneShot.model_fields)


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
    graph = _full_video()
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
    """三视图和关键帧都要**带一组参考图**出图;每一镜都给首帧或参考素材,不只给一段文字。
    默认模型不合用时绕开它挑一个合用的;一个都没有就留空(界面会让他去选)。"""

    def _model(self, db, owner: str, vendor: str, model_id: str, capability: str):
        from app.db.models import ProviderModel, ProviderProfile

        profile = ProviderProfile(owner_user_id=owner, vendor=vendor, name=vendor, enabled=True)
        db.add(profile)
        db.flush()
        row = ProviderModel(provider_profile_id=profile.id, model_id=model_id, enabled=True, capability_ids=[capability])
        db.add(row)
        db.flush()
        return row

    def test_判断规则(self) -> None:
        from app.domain.workflows.templates import _can_shoot_from_references, _can_take_references

        assert _can_take_references(None, SEEDREAM), "Seedream 4 收 14 张参考图"
        assert not _can_take_references(None, ModelChoice(provider="bytedance", model="doubao-seedream-3-0-t2i-250415")), "只会文生图"
        assert _can_shoot_from_references(None, SEEDANCE)
        assert not _can_shoot_from_references(None, ModelChoice()), "没有模型不算能"

    def test_默认图像模型只会文生图时换一个能带参考的(self) -> None:
        from app.core.db import SessionLocal
        from app.domain.provider_defaults import set_default
        from app.domain.workflows.templates import _reference_image_model
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            t2i = self._model(db, "u1", "bytedance", "doubao-seedream-3-0-t2i-250415", "image")
            i2i = self._model(db, "u1", "bytedance", "doubao-seedream-4-0-250828", "image")
            set_default(db, "image", t2i, owner_user_id="u1")
            db.commit()
            assert _reference_image_model(db, "u1").model == i2i.model_id

    def test_一个合用的都没有就留空(self) -> None:
        from app.core.db import SessionLocal
        from app.domain.workflows.templates import _reference_image_model
        from tests.util import fresh_client

        fresh_client()
        with SessionLocal() as db:
            self._model(db, "u1", "bytedance", "doubao-seedream-3-0-t2i-250415", "image")
            db.commit()
            assert _reference_image_model(db, "u1").model == ""


class Test分镜写了口播就要真的配上:
    """分镜的 schema 给每镜留了 narration,创意简报、脚本、分镜三步都在为它服务 ——
    而此前**没有任何一个节点用它**,成片是默哑的。写了却不用,比不写更容易让人以为是坏了。
    """

    def _loops(self, voice_id: str = "v1") -> tuple[dict[str, Any], dict[str, Any]]:
        """(各镜同时生成, 按镜头顺序接上时间线) 两个循环的 config。"""
        graph = _full_video(voice_id=voice_id)
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
        # 画面那条从白模开始(白模 → 首帧/尾帧 → 视频)。
        roots = {n["id"] for n in generate["body"]["nodes"]} - {e["target"] for e in generate["body"]["edges"]}
        assert {"render_blockout", "has_voice"} <= roots


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

    workflows = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows"
    #: **两份模板文件都要扫。** 只扫 templates.py 的话,新加的那个文件天生免检 ——
    #: 而"漏一种语言"恰恰是新写模板时最容易犯的。
    sources = [workflows / "templates.py", workflows / "templates_business.py"]
    missing = []
    for node in ast.walk(ast.parse("\n".join(one.read_text(encoding="utf-8") for one in sources))):
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


# --------------------------------------------------------------------------------------
# 起点是「用户手里已有的东西」的那四个模板
# --------------------------------------------------------------------------------------

from app.domain.workflows.templates import MAX_SHOTS_CEILING, TEMPLATE_CATALOG  # noqa: E402
from app.domain.workflows.templates_business import (  # noqa: E402
    BUSINESS_TEMPLATE_CATALOG,
    fabric_lookbook_graph,
    footage_montage_graph,
    highlight_shorts_graph,
    product_on_model_graph,
    product_pitch_short_graph,
)


def _business_graphs() -> dict[str, dict[str, Any]]:
    return {
        "highlight_shorts": highlight_shorts_graph(chat=CHAT),
        "product_on_model": product_on_model_graph(chat=CHAT, image=SEEDREAM, video=SEEDANCE),
        "product_pitch_short": product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="voice-1"),
        "fabric_lookbook": fabric_lookbook_graph(chat=CHAT, image=SEEDREAM),
        "footage_montage": footage_montage_graph(chat=CHAT, voice_id="voice-1"),
    }


def test_四个新模板的图和循环体都成立() -> None:
    """和三个老模板同一套判据:图本身合法,而且**每一处 `{{…}}` 都指得到东西**。

    引用写错在这里不会报错 —— 跑起来才发现取到空值,而那时已经花掉了几次付费调用。
    """
    for template_id, graph in _business_graphs().items():
        # 素材那一格是**留给用户装好模板之后自己挑的**,所以不要求它已经填上
        # (和 transcript_video_cleanup 同一条)。
        assert validate_graph(graph, require_config=False) == [], template_id
        assert _invalid_references(graph) == [], template_id
        assert graph["meta"]["template_id"] == template_id
        assert graph["meta"]["source"] == "official"
        for node in graph["nodes"]:
            body = (node.get("config") or {}).get("body")
            if isinstance(body, dict):
                assert validate_graph(body, require_start=False) == [], f"{template_id}/{node['id']}"
                assert _invalid_references(body, virtual_roots={"loop", "input"}) == [], f"{template_id}/{node['id']}"


def test_切片模板不花任何生成费用() -> None:
    """它的全部价值就在这里:转写 + 一次对话 + 截取 + 导出,**没有一次付费生成**。

    哪天有人往里加一个 ai_generate,这条会红 —— 那时它就不再是"门槛最低的那个模板"了,
    模板卡片上「不花生成费用」那句话也就成了谎。
    """
    graph = highlight_shorts_graph(chat=CHAT)
    kinds = {node["type"] for node in graph["nodes"]}
    for node in graph["nodes"]:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict):
            kinds |= {inner["type"] for inner in body["nodes"]}
    assert "ai_generate" not in kinds
    assert "synthesize_speech" not in kinds


def test_切片的字幕时间码相对自己那一条() -> None:
    """切出来的序列从 0 开始,字幕当然也要从 0 开始。

    漏掉这一条的表现很隐蔽:片子能导出、字幕也在,只是全都跑到片尾之后去了 —— 看着像没有字幕。
    """
    graph = highlight_shorts_graph(chat=CHAT)
    loop = _node(graph, "cut_clips")
    captions = next(one for one in loop["config"]["body"]["nodes"] if one["id"] == "burn_captions")
    assert captions["config"]["segments"] == "{{loop.item.captions}}"
    assert captions["config"]["offset"] == 0
    #: 提示词里必须写明这一点,否则模型给的是原片时间。
    assert "相对" in _node(graph, "highlights")["config"]["system"]


def test_商品图贯穿每一次生成() -> None:
    """这几个模板的全部要点:生成的是「这件东西在别处」,不是「一件像它的东西」。

    商品图**每一次生成都要带上**,不是只喂第一次;视频那一步还要把刚出的上身图当首帧,
    否则动起来的那个人可能换了一身衣服。
    """
    graph = product_on_model_graph(chat=CHAT, image=SEEDREAM, video=SEEDANCE)
    body = _node(graph, "shoot_scenes")["config"]["body"]["nodes"]
    image_node = next(one for one in body if one["id"] == "on_model")
    assert "{{input.product_asset_id}}:reference_image" in image_node["config"]["source_assets"]
    assert "EXACTLY" in image_node["config"]["prompt"]
    assert image_node["config"]["negative_prompt"]

    clip = next(one for one in body if one["id"] == "on_model_clip")
    assert "{{on_model.asset_id}}:first_frame" in clip["config"]["source_assets"]
    assert "{{input.product_asset_id}}:reference_image" in clip["config"]["source_assets"]


def test_没有视频模型时上身图模板仍然可用() -> None:
    """视频是**可选**的一步。没有合适的视频模型就只出静图,而不是让整条模板用不了 ——
    服装客户最常见的诉求本来就是"给我几张能投的图"。"""
    graph = product_on_model_graph(chat=CHAT, image=SEEDREAM, video=ModelChoice())
    body = _node(graph, "shoot_scenes")["config"]["body"]["nodes"]
    assert {one["id"] for one in body} == {"on_model", "file_image"}
    assert validate_graph(graph, require_config=False) == []
    #: 计划里也不该再要视频提示词 —— 要了就是让模型白写一段没人用的东西。
    scene_props = _node(graph, "lookbook_plan")["config"]["json_schema"]["properties"]["scenes"]["items"]
    assert "video_prompt" not in scene_props["properties"]


def test_带货短片的画面必须按拍顺序落位() -> None:
    """并发的落位顺序是谁先回来谁在前 —— 画面就和口播对不上了。"""
    graph = product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="voice-1")
    assert _node(graph, "shoot_beats")["config"]["concurrency"] == 1


def test_面料规格页不许编数字() -> None:
    """成分、克重、幅宽是要负责任的数字,编一个出来比不写更糟。"""
    graph = fabric_lookbook_graph(chat=CHAT, image=SEEDREAM)
    system = _node(graph, "fabric_plan")["config"]["system"]
    assert "只能复述用户给出的参数" in system
    assert "需与工厂确认" in system
    #: 发给客户的那一页要自己带免责声明 —— 效果图是生成的,不是实拍。
    assert "以工厂实测为准" in _node(graph, "spec_note")["config"]["markdown"]


def test_模板卡片和图一一对应() -> None:
    """卡片是用户**照着判断自己能不能跑**的那份东西。有卡片没图 = 点了报错;
    有图没卡片 = 这个模板根本没人找得到。"""
    from app.domain.workflows.templates import (
        FABRIC_LOOKBOOK,
        FULL_VIDEO_GENERATION,
        HIGHLIGHT_SHORTS,
        PRODUCT_ON_MODEL,
        FOOTAGE_MONTAGE,
        PRODUCT_PITCH_SHORT,
        TRANSCRIPT_VIDEO_CLEANUP,
        TRANSLATED_DUB,
    )

    known = {
        FULL_VIDEO_GENERATION, TRANSCRIPT_VIDEO_CLEANUP, TRANSLATED_DUB,
        HIGHLIGHT_SHORTS, PRODUCT_ON_MODEL, PRODUCT_PITCH_SHORT, FABRIC_LOOKBOOK, FOOTAGE_MONTAGE,
    }
    assert {card["id"] for card in TEMPLATE_CATALOG} == known
    for card in BUSINESS_TEMPLATE_CATALOG:
        for field in ("name", "summary"):
            assert {"zh", "en"} <= set(card[field]), f"{card['id']}.{field}"
        for field in ("requires", "stages"):
            assert {"zh", "en"} <= set(card[field]), f"{card['id']}.{field}"
            assert card[field]["zh"] and card[field]["en"], f"{card['id']}.{field} 是空的"


def test_镜头数有一道成本闸门() -> None:
    """每一镜都是一次付费的视频生成,而镜头数此前完全由模型按时长算 —— 跑之前看不到要花多少。

    用户那个数走提示词(他可以调),schema 上另有一道硬天花板;两者**故意拉开距离** ——
    贴太近的话模型多给一镜就是整条流程作废,而那正是要避免的失败方式。
    """
    graph = _full_video()
    default = _node(graph, "start")["config"]["params"]["max_shots"]
    storyboard = _node(graph, "storyboard")["config"]
    assert storyboard["json_schema"]["properties"]["shots"]["maxItems"] == MAX_SHOTS_CEILING
    assert MAX_SHOTS_CEILING > default * 2, "天花板要比默认值宽出一截"
    assert "{{start.max_shots}}" in storyboard["prompt"]
    #: 和上限打架时缩短成片,而不是压缩单镜 —— 单镜时长是视频模型的固定档位,压不了。
    assert "以上限为准" in storyboard["prompt"]


def test_混剪的音画按每一段自己的起点对齐() -> None:
    """口播不是一条音轨铺到底 —— 每一段的旁白落在**这一段自己的起点**上。

    那个起点由 `timeline_append` 运行时回报,不是算出来的:前面几段实际多长不重要,音画都落在
    同一个数上。改成累计求和的话,某一段稍短一点,后面全部越走越偏,而成片看起来是完整的 ——
    要有人从头听一遍才发现对不上。字幕用同一个起点做偏移,所以两者永远同步。
    """
    graph = footage_montage_graph(chat=CHAT, voice_id="voice-1")
    loop = _node(graph, "lay_segments")["config"]
    #: 归一化把 `{{place_shot.timeline_start}}` 落成了**数据边** —— 于是它同时是一条真实依赖:
    #: 旁白和字幕都等这一段接上去、拿到它的落点之后才动。
    bindings = {
        (edge["source"], edge["source_output"], edge["target"], edge["target_input"])
        for edge in loop["body"]["edges"]
        if edge.get("kind") == "data"
    }
    assert ("place_shot", "timeline_start", "place_voice", "at") in bindings
    assert ("place_shot", "timeline_start", "caption_shot", "offset") in bindings
    #: 顺序就是叙事,不能并发。
    assert loop["concurrency"] == 1


def test_混剪没有音色也能用() -> None:
    """很多企业片本来就是纯字幕。旁白那两步由条件挡掉,字幕照出 ——
    而不是让整条模板因为没克隆过嗓子就用不了。"""
    graph = footage_montage_graph(chat=CHAT, voice_id="")
    body = {one["id"]: one for one in _node(graph, "lay_segments")["config"]["body"]["nodes"]}
    assert body["has_voice"]["config"] == {"left": "{{input.voice_id}}", "op": "not_empty"}
    #: 字幕不挂在那个条件后面 —— 它和有没有旁白无关,只等这一段的落点。
    edges = _node(graph, "lay_segments")["config"]["body"]["edges"]
    into_caption = {edge["source"] for edge in edges if edge["target"] == "caption_shot"}
    assert into_caption == {"place_shot"}
    assert body["caption_shot"]["config"]["allow_empty"] == "yes"


def test_混剪是从一批素材出发的() -> None:
    """此前每个模板的起点都是**一条**素材。企业手里是一堆,而"先讲什么后讲什么"正是要让模型做的事。"""
    graph = footage_montage_graph(chat=CHAT, voice_id="voice-1")
    assert _node(graph, "footage")["type"] == "asset_query"
    assert _node(graph, "footage")["config"]["kind"] == "video"
    #: 清单要进提示词,否则模型无从挑起。
    prompt = _node(graph, "montage_plan")["config"]["prompt"]
    assert "{{footage.assets}}" in prompt
    #: id 抄错这一段就是空的,所以提示词和 schema 都要说死。
    system = _node(graph, "montage_plan")["config"]["system"]
    assert "原样抄" in system
    segment = _node(graph, "montage_plan")["config"]["json_schema"]["properties"]["segments"]["items"]
    assert "原样抄" in segment["properties"]["asset_id"]["description"]


def test_混剪不生成任何画面() -> None:
    """画面就是用户自己的素材。哪天有人往里加一个 ai_generate,卡片上那句话就成了谎。"""
    graph = footage_montage_graph(chat=CHAT, voice_id="voice-1")
    kinds = {node["type"] for node in graph["nodes"]}
    for node in graph["nodes"]:
        body = (node.get("config") or {}).get("body")
        if isinstance(body, dict):
            kinds |= {inner["type"] for inner in body["nodes"]}
    assert "ai_generate" not in kinds


def test_白模的台距由布景尺寸算出来_而不是写死() -> None:
    """用户报的「3D 白模的位置、布局非常奇怪」就是这一条。

    此前提示词写死「第 n 镜的布景台放在 x = n*40」。而一间三四米宽的卧室按 40 米排开,台与台
    之间空出三十多米 —— 实测那个场景八个台摊在 320 米上,视口里是一串看不清的小点。
    反过来也不对:视觉圣经允许 60 米的大场景,那在 40 米台距下会直接和隔壁穿模 ——
    这个常数本来就是为了"互不干扰"存在的,结果两头都不成立。
    """
    system = _node(_full_video(), "set_design")["config"]["system"]
    assert "x = n*40" not in system
    assert "不要用固定的 40 米" in system
    #: 台距要从视觉圣经里的场景尺寸推出来。
    assert "width_m" in system and "台距" in system


def test_每个布景台收进一个组() -> None:
    """八个台摊平就是七十多条重名的列表(「出租屋卧室」出现八次),谁也分不出哪个是哪个。

    组**放在原点**,所以它只负责收纳、不改变任何坐标 —— 相机与渲染那套算法一点不用动。
    """
    graph = _full_video()
    props = _node(graph, "set_design")["config"]["json_schema"]["properties"]["objects"]["items"]["properties"]
    assert "parent_id" in props, "schema 里没有 parent_id 的话,模型根本分不了组"
    assert "group" in props["kind"]["enum"]
    system = _node(graph, "set_design")["config"]["system"]
    assert 'id="bay-<n>"' in system
    assert "不改变任何坐标" in system


def test_布景台的组是场景格式本来就支持的() -> None:
    """不是新发明一个概念:SceneContent 早就有 group 和 parent_id,只是模板的 schema 没放开。
    所以 scene_create 那一步一个字都不用改。"""
    import typing

    from app.domain.scene_types import SceneObject

    kinds = typing.get_args(SceneObject.model_fields["kind"].annotation)
    assert "group" in kinds, kinds
    assert "parent_id" in SceneObject.model_fields
