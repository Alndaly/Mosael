"""把官方业务模板**整张图真跑一遍** —— 只把花钱 / 连外部的那几个节点换成假的,其余(条件、循环、接时间线、字幕、
改音量、建项目、按标签取素材、归档、笔记)全是真的执行器,走真的 `engine.execute_graph`。

此前的模板测试只看"引用指得到东西",从不跑循环体。于是这些错一个都没被抓到:

- 混剪:这一段没有旁白(或者根本没配音色)时,「放旁白」拿着空素材照跑 —— 控制边在规范化时被折进了同一对节点
  之间的数据边,而只剩数据边时任一上游跑过就算激活;
- 混剪:每一段只给了起点,「接到时间线」没有终点就取到素材末尾;
- 带货口播:只念了钩子和号召,各拍的旁白一句都没合成,也没有字幕;每拍的画面按图片默认的 5 秒铺,和脚本对不上;
- 上身图:带视频时循环只交视频,图不在结果里。

假节点只是"不花钱":它们按配置造出素材、记下每一次调用;生成那一个还顺手按内置模型的能力表把这一次的参数和素材
组合校验一遍(和生成漏斗在提交前做的是同一个函数)。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

import jsonschema
import pytest

from app.core.unit_of_work import unit_of_work
from app.db.models import Asset, Clip, Note, Project, Sequence, Track, Workflow
from app.domain.generation.operations import keep_source_group, parse_source_assets, validate_against_capabilities
from app.domain.workflows import WorkflowDomainError, validate_graph, with_run_params
from app.domain.workflows import executors as registry
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.templates import ModelChoice, full_video_generation_graph
from app.domain.workflows.templates_business import (
    DUCKED_SOURCE_GAIN,
    fabric_lookbook_graph,
    footage_montage_graph,
    highlight_shorts_graph,
    product_on_model_graph,
    product_pitch_short_graph,
    talking_script_video_graph,
)
from tests.test_scene_workflow_nodes import _import_glb
from tests.util import fresh_client, make_voice

CHAT = ModelChoice(profile_id="chat", provider="openai", model="chat-model")
SEEDREAM = ModelChoice(profile_id="image", provider="bytedance", model="doubao-seedream-4-0-250828")
SEEDANCE = ModelChoice(profile_id="video", provider="bytedance", model="doubao-seedance-2-0-260128")
VEO = ModelChoice(profile_id="video", provider="google", model="veo")


class Studio:
    """假的付费 / 外部节点。`plans` 按 json_schema_name 给对话节点的回答(先按那一步的 schema 校验一遍)。"""

    def __init__(self, monkeypatch, workspace_id: str, plans: dict[str, Any]) -> None:
        self.workspace_id = workspace_id
        self.plans = plans
        self.calls: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.speech_seconds: dict[str, float] = {}
        self.presenter: dict[str, Any] = {"entity_id": "presenter-1", "found": 1, "voice_engine": "builtin:clone",
                                          "voice_id": "voice-of-presenter", "asset_ids": ["presenter-face"]}
        for node_type, handler in {
            "llm": self.llm,
            "ai_generate": self.generate,
            "synthesize_speech": self.speak,
            "talking_segments": self.segments,
            "image_speak": self.video_node("image_speak"),
            "entity_speak": self.video_node("entity_speak"),
            "entity_get": self.entity_get,
            "transcribe_asset": self.transcribe,
            "export_sequence": self.export,
        }.items():
            monkeypatch.setitem(registry._REGISTRY, node_type, handler)

    def _asset(self, db, kind: str, name: str, media_info: dict[str, Any]) -> str:
        asset = Asset(workspace_id=self.workspace_id, kind=kind, name=name, source="generated",
                      file_key=f"k-{kind}-{len(self.calls)}-{name}", media_info=media_info)
        db.add(asset)
        db.flush()
        return asset.id

    def llm(self, db, scope, config):
        name = config["json_schema_name"]
        plan = self.plans[name]
        #: 假回答也得是这一步要的形状 —— 否则测的是一张模板里根本不会出现的数据。
        jsonschema.validate(plan, config["json_schema"])
        self.calls["llm"].append({"name": name, "prompt": config["prompt"]})
        return {"text": json.dumps(plan, ensure_ascii=False), "json": plan, "response_format_used": "json_schema"}

    def generate(self, db, scope, config):
        kind = config["kind"]
        parameters = dict(config.get("parameters") or {})
        sources = keep_source_group(parse_source_assets(config.get("source_assets"), kind=kind),
                                    str(config.get("source_group") or "all").strip())
        #: 生成漏斗提交前的那一道:参数和素材组合这个模型认不认。
        validate_against_capabilities(config["provider"], config["model"], kind, parameters, sources)
        self.calls["ai_generate"].append({**config, "sources": sources})
        if kind == "video":
            media = {"duration": float(parameters.get("duration_seconds") or 5)}
        else:
            media = {"width": 720, "height": 1280}
        return {"asset_id": self._asset(db, kind, f"gen-{kind}", media), "asset_ids": [], "generation_id": ""}

    def speak(self, db, scope, config):
        assert str(config.get("voice") or "").strip(), f"没带音色就去合成了:{config}"
        self.calls["synthesize_speech"].append(config)
        seconds = self.speech_seconds.get(config["text"], max(1.0, len(config["text"]) / 4))
        return {"asset_id": self._asset(db, "audio", config["text"], {"duration": seconds})}

    def segments(self, db, scope, config):
        self.calls["talking_segments"].append(config)
        audio = [self._asset(db, "audio", f"seg-{index}", {"duration": 6.0}) for index in range(2)]
        return {
            "segments": [{"audio_asset_id": one, "text": f"第 {index} 段"} for index, one in enumerate(audio)],
            "cues": [{"start": 0, "end": 6, "text": "第 0 段"}, {"start": 6, "end": 12, "text": "第 1 段"}],
            "count": 2, "duration": 12.0,
        }

    def video_node(self, node_type: str):
        def run(db, scope, config):
            self.calls[node_type].append(config)
            return {"asset_id": self._asset(db, "video", node_type, {"duration": 6.0}), "asset_ids": [], "audio_asset_id": ""}
        return run

    def entity_get(self, db, scope, config):
        self.calls["entity_get"].append(config)
        if not str(config.get("entity_id") or "").strip():
            raise WorkflowDomainError("wfErr_entityGetNeedsTarget")
        return {"name": "主播", "description": "", "prompt": "", "asset_ids": [], "asset_id": "", **self.presenter}

    def transcribe(self, db, scope, config):
        self.calls["transcribe_asset"].append(config)
        return {"text": "", "timed_text": "[]", "segments": [], "language": "zh", "transcript_id": "", "duration": 600}

    def export(self, db, scope, config):
        self.calls["export_sequence"].append(config)
        return {"asset_id": f"export-of-{config['sequence_id']}"}


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _workflow(ws: str) -> str:
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _asset(ws: str, kind: str, name: str, *, tags: list[str] | None = None, **media: Any) -> str:
    with unit_of_work() as db:
        asset = Asset(workspace_id=ws, kind=kind, name=name, source="imported", file_key=f"k-{name}",
                      media_info=media, tags=tags or [])
        db.add(asset)
        db.commit()
        return asset.id


def _tagged_video(ws: str, name: str, seconds: float, tag: str) -> str:
    return _asset(ws, "video", name, tags=[tag], duration=seconds)


def _pick(graph: dict[str, Any], node_id: str, **config: Any) -> dict[str, Any]:
    """把用户在画布上会填的那几格填上(素材、主播……)。"""
    node = next(one for one in graph["nodes"] if one["id"] == node_id)
    node["config"].update(config)
    return graph


def _run(ws: str, graph: dict[str, Any], **params: Any) -> dict[str, Any]:
    #: 先过运行前的那一道(和真按下运行时同一份判据,连同这一次带的参数):图本身得是一张能启动的图。
    errors = validate_graph(with_run_params(graph, params))
    assert errors == [], errors
    context, cancelled = execute_graph(graph, wf_id=_workflow(ws), params=params)
    assert not cancelled
    return context


def _clips(sequence_id: str, kind: str) -> list[Clip]:
    with unit_of_work() as db:
        tracks = db.query(Track).filter(Track.sequence_id == sequence_id, Track.kind == kind).all()
        clips = [clip for track in tracks for clip in track.clips]
        for clip in clips:
            db.expunge(clip)
        return sorted(clips, key=lambda clip: clip.timeline_start)


def _span(clip: Clip) -> float:
    return (clip.src_out - clip.src_in) / (clip.speed or 1.0)


# --------------------------------------------------------------------------------------
# 混剪
# --------------------------------------------------------------------------------------


def _segment(asset_id: str, start: float, end: float, narration: str, caption: str) -> dict[str, Any]:
    return {
        "segment_title": caption, "asset_id": asset_id, "source_name": caption,
        "src_start": start, "src_end": end, "seconds": end - start, "narration": narration,
        "captions": [{"start": 0, "end": end - start, "text": caption}], "why": "",
    }


class Test混剪真跑:
    def _plan(self, ws: str) -> tuple[dict[str, Any], list[str]]:
        workshop = _tagged_video(ws, "车间", 30.0, "厂区")
        line = _tagged_video(ws, "产线", 40.0, "厂区")
        _tagged_video(ws, "别的片子", 10.0, "别处")
        plan = {
            "storyline": "从车间到产线",
            "segments": [
                _segment(workshop, 4.0, 10.0, "这是我们的车间", "车间"),
                #: 这一段没有旁白 —— 正是会让「放旁白」拿着空素材照跑的那种。
                _segment(line, 12.0, 17.0, "", "产线"),
                _segment(workshop, 20.0, 26.0, "每一件都从这里出发,念得比这一段还要长一些才对", "出发"),
            ],
            "unused_note": "",
        }
        return plan, [workshop, line]

    def test_有音色时_没旁白的那段不放旁白_每段按起止截取_旁白底下压低原声(self, monkeypatch) -> None:
        ws = _workspace()
        plan, _ = self._plan(ws)
        studio = Studio(monkeypatch, ws, {"footage_montage_plan": plan})
        graph = footage_montage_graph(chat=CHAT, voice_id="voice-1")
        context = _run(ws, graph, topic="工厂介绍", footage_tag="厂区")

        sequence_id = context["montage_project"]["sequence_id"]
        video = _clips(sequence_id, "video")
        #: 每一段就是 src_start..src_end 那一截,不是从起点一直取到素材末尾。
        assert [(clip.src_in, clip.src_out) for clip in video] == [(4.0, 10.0), (12.0, 17.0), (20.0, 26.0)]
        assert [clip.timeline_start for clip in video] == [0.0, 6.0, 11.0]

        audio = _clips(sequence_id, "audio")
        assert [clip.timeline_start for clip in audio] == [0.0, 11.0], "没旁白的那一段不该有旁白"
        assert _span(audio[1]) <= 6.0 + 1e-6, "旁白比这一段长,要压进这一段,不能盖到下一段"
        assert [one["text"] for one in studio.calls["synthesize_speech"]] == [plan["segments"][0]["narration"],
                                                                              plan["segments"][2]["narration"]]
        #: 有旁白的那两段,原声压低;没旁白的那段原声照旧。
        assert [clip.gain for clip in video] == [DUCKED_SOURCE_GAIN, 1.0, DUCKED_SOURCE_GAIN]
        subtitles = _clips(sequence_id, "subtitle")
        assert [(clip.timeline_start, clip.text_override) for clip in subtitles] == [(0.0, "车间"), (6.0, "产线"), (11.0, "出发")]
        assert context["output"]["output"]["final_asset_id"] == f"export-of-{sequence_id}"

    def test_素材比截取短_旁白和字幕都按实际长度收住_念不完的裁掉并通知(self, monkeypatch) -> None:
        from app.db.models import Notification

        ws = _workspace()
        short = _tagged_video(ws, "短素材", 8.0, "厂区")
        long_ = _tagged_video(ws, "长素材", 30.0, "厂区")
        #: 计划从第 4 秒取到第 12 秒,素材只有 8 秒:这一段实际只有 4 秒。旁白念 8 秒,加速 1.5 倍也要 5.3 秒。
        first = _segment(short, 4.0, 12.0, "这一段旁白写得比素材长", "短")
        first["captions"] = [{"start": 0, "end": 4, "text": "前半"}, {"start": 4, "end": 8, "text": "后半"}]
        plan = {"storyline": "", "segments": [first, _segment(long_, 0.0, 6.0, "第二段", "长")], "unused_note": ""}
        studio = Studio(monkeypatch, ws, {"footage_montage_plan": plan})
        studio.speech_seconds[first["narration"]] = 8.0
        context = _run(ws, footage_montage_graph(chat=CHAT, voice_id="voice-1"), topic="工厂介绍", footage_tag="厂区")

        sequence_id = context["montage_project"]["sequence_id"]
        assert [(clip.timeline_start, _span(clip)) for clip in _clips(sequence_id, "video")] == [(0.0, 4.0), (4.0, 6.0)]
        audio = _clips(sequence_id, "audio")
        assert [clip.timeline_start for clip in audio] == [0.0, 4.0]
        assert _span(audio[0]) == pytest.approx(4.0), "旁白最长就是这一段实际的 4 秒,不是计划的 8 秒 —— 不盖到下一段"
        subtitles = [(clip.timeline_start, clip.timeline_start + _span(clip), clip.text_override)
                     for clip in _clips(sequence_id, "subtitle")]
        assert subtitles == [(0.0, 4.0, "前半"), (4.0, 10.0, "长")], "落在这一段之后的字幕不上屏"
        with unit_of_work() as db:
            notices = [one.title for one in db.query(Notification).filter(Notification.workspace_id == ws)]
        assert "混剪:有一段旁白念不完" in notices

    def test_没有音色时整条只出字幕(self, monkeypatch) -> None:
        ws = _workspace()
        plan, _ = self._plan(ws)
        studio = Studio(monkeypatch, ws, {"footage_montage_plan": plan})
        context = _run(ws, footage_montage_graph(chat=CHAT, voice_id=""), topic="工厂介绍", footage_tag="厂区")
        sequence_id = context["montage_project"]["sequence_id"]
        assert studio.calls["synthesize_speech"] == []
        assert _clips(sequence_id, "audio") == []
        assert [clip.gain for clip in _clips(sequence_id, "video")] == [1.0, 1.0, 1.0]
        assert len(_clips(sequence_id, "subtitle")) == 3

    def test_只取这个标签下的视频_清单交给模型(self, monkeypatch) -> None:
        ws = _workspace()
        plan, ids = self._plan(ws)
        studio = Studio(monkeypatch, ws, {"footage_montage_plan": plan})
        context = _run(ws, footage_montage_graph(chat=CHAT, voice_id=""), topic="工厂介绍", footage_tag="厂区")
        assert context["footage"]["count"] == 2
        prompt = studio.calls["llm"][0]["prompt"]
        assert all(one in prompt for one in ids) and "别的片子" not in prompt

    def test_标签下的素材超过六十条_照样都交给模型(self, monkeypatch) -> None:
        ws = _workspace()
        plan, ids = self._plan(ws)
        more = [_tagged_video(ws, f"补拍 {index}", 10.0, "厂区") for index in range(70)]
        studio = Studio(monkeypatch, ws, {"footage_montage_plan": plan})
        context = _run(ws, footage_montage_graph(chat=CHAT, voice_id=""), topic="工厂介绍", footage_tag="厂区")
        assert context["footage"]["count"] == 72, "此前只取 60 条,多出来的悄悄不进清单"
        assert more[-1] in studio.calls["llm"][0]["prompt"]

    def test_标签没填运行前就拦住(self) -> None:
        #: 标签空着的话「按标签取」取到的是整个素材库。
        errors = validate_graph(footage_montage_graph(chat=CHAT, voice_id="voice-1"))
        assert any("params.footage_tag" in one for one in errors), errors

    def test_标签下没有素材_停下说清楚_不花对话的钱(self, monkeypatch) -> None:
        ws = _workspace()
        _tagged_video(ws, "车间", 30.0, "厂区")
        studio = Studio(monkeypatch, ws, {})
        graph = footage_montage_graph(chat=CHAT, voice_id="voice-1")
        context = _run(ws, graph, topic="工厂介绍", footage_tag="没有这个标签")
        assert studio.calls["llm"] == [], "没有素材还去问模型,它只能编 id"
        assert "no_footage_notice" in context and "montage_project" not in context
        with unit_of_work() as db:
            assert db.query(Project).filter(Project.workspace_id == ws).count() == 0, "不该留下一个空项目"


# --------------------------------------------------------------------------------------
# 带货口播(不出镜 / 出镜)
# --------------------------------------------------------------------------------------

LONG_NARRATION = "这一拍的话写得太长了一点,念出来远远超过这一拍给的四秒钟"
BEATS = [
    {"narration": "别再买起球的毛衣", "seconds": 3, "visual_prompt": "sweater on a chair", "caption": "不起球"},
    {"narration": LONG_NARRATION, "seconds": 4, "visual_prompt": "close-up of the knit", "caption": "细密针织"},
    {"narration": "点下面链接带走它", "seconds": 3, "visual_prompt": "folded sweater", "caption": "链接在下面"},
]


class Test带货口播真跑:
    def test_每一拍都配音_画面按脚本时长_画外音对齐这一拍_字幕按落点(self, monkeypatch) -> None:
        ws = _workspace()
        studio = Studio(monkeypatch, ws, {"product_pitch_script": {"beats": BEATS}})
        graph = _pick(product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="voice-1"),
                      "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        context = _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        sequence_id = context["pitch_project"]["sequence_id"]

        video = _clips(sequence_id, "video")
        assert [clip.timeline_start for clip in video] == [0.0, 3.0, 7.0]
        assert [_span(clip) for clip in video] == [3.0, 4.0, 3.0], "每一拍按脚本的 seconds 铺,不是图片默认的 5 秒"

        #: 钩子和号召就是首尾两拍 —— 每一拍都念,不再另合成一段「钩子 + 号召」放在 0 秒。
        assert [one["text"] for one in studio.calls["synthesize_speech"]] == [beat["narration"] for beat in BEATS]
        assert {one["voice"] for one in studio.calls["synthesize_speech"]} == {"voice-1"}
        audio = _clips(sequence_id, "audio")
        assert [clip.timeline_start for clip in audio] == [0.0, 3.0, 7.0]
        assert _span(audio[1]) < len(LONG_NARRATION) / 4, "念得比这一拍长的那段要加速,不能压到下一拍的话上"

        subtitles = _clips(sequence_id, "subtitle")
        assert [(clip.timeline_start, clip.text_override) for clip in subtitles] == [
            (0.0, "不起球"), (3.0, "细密针织"), (7.0, "链接在下面")]
        #: 竖屏成片的画面按竖屏那一档出图 —— 不传尺寸时 Seedream 出 2048 的方图,两侧被裁掉。
        assert {one["parameters"].get("size") for one in studio.calls["ai_generate"]} == {"720x1280"}
        #: 每一拍的画面都是付过钱的素材,归进这条短片的项目。
        with unit_of_work() as db:
            filed = db.query(Asset).filter(Asset.project_id == context["pitch_project"]["project_id"],
                                           Asset.kind == "image").count()
        assert filed == 3

    def test_最后一拍念不完_裁到这一拍的末尾_成片尾不留黑(self, monkeypatch) -> None:
        ws = _workspace()
        beats = [dict(BEATS[0]), dict(BEATS[1]), {**BEATS[2], "narration": "号" * 40, "seconds": 2.5}]
        Studio(monkeypatch, ws, {"product_pitch_script": {"beats": beats}})
        graph = _pick(product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="voice-1"),
                      "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        context = _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        sequence_id = context["pitch_project"]["sequence_id"]
        video_end = max(clip.timeline_start + _span(clip) for clip in _clips(sequence_id, "video"))
        audio_end = max(clip.timeline_start + _span(clip) for clip in _clips(sequence_id, "audio"))
        assert video_end == pytest.approx(9.5)
        assert audio_end <= video_end + 1e-6, "画外音比画面长,成片尾是一截黑屏"

    def test_出镜版_开场各拍收尾依次接上_每拍用主播的嗓子_也有字幕(self, monkeypatch) -> None:
        ws = _workspace()
        script = {"hook_line": "你家毛衣是不是一洗就起球", "beats": BEATS, "call_to_action": "现在下单"}
        studio = Studio(monkeypatch, ws, {"product_pitch_script": script})
        graph = product_pitch_short_graph(chat=CHAT, image=SEEDREAM, presenter=True)
        _pick(graph, "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        _pick(graph, "presenter", entity_id="presenter-1")
        context = _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        sequence_id = context["pitch_project"]["sequence_id"]

        video = _clips(sequence_id, "video")
        assert [clip.timeline_start for clip in video] == [0.0, 6.0, 9.0, 13.0, 16.0], "开场 → 三拍 → 收尾"
        #: 开场和收尾两段同时生成(谁先回来不一定),落位顺序由连线定 —— 上面那条已经看过了。
        assert sorted(one["text"] for one in studio.calls["entity_speak"]) == sorted([script["hook_line"], script["call_to_action"]])
        assert {one["voice"] for one in studio.calls["synthesize_speech"]} == {"voice-of-presenter"}
        assert [clip.timeline_start for clip in _clips(sequence_id, "audio")] == [6.0, 9.0, 13.0]
        assert [clip.timeline_start for clip in _clips(sequence_id, "subtitle")] == [6.0, 9.0, 13.0]

    def test_某一拍没有画外音_这一拍只铺画面_整条照样成片(self, monkeypatch) -> None:
        from app.domain.workflows.executors.subjobs import synthesize_speech as real_speak

        ws = _workspace()
        beats = [dict(BEATS[0]), {**BEATS[1], "narration": ""}, dict(BEATS[2])]
        studio = Studio(monkeypatch, ws, {"product_pitch_script": {"beats": beats}})

        def speak(db, scope, config):
            #: 空文本交给真的合成节点 —— 它当场拒(「合成文本不能为空」),就是此前整条失败的那一下。
            return real_speak(db, scope, config) if not config["text"].strip() else studio.speak(db, scope, config)

        monkeypatch.setitem(registry._REGISTRY, "synthesize_speech", speak)
        graph = _pick(product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="voice-1"),
                      "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        context = _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        sequence_id = context["pitch_project"]["sequence_id"]
        assert [clip.timeline_start for clip in _clips(sequence_id, "video")] == [0.0, 3.0, 7.0]
        assert [one["text"] for one in studio.calls["synthesize_speech"]] == [BEATS[0]["narration"], BEATS[2]["narration"]]
        assert [clip.timeline_start for clip in _clips(sequence_id, "audio")] == [0.0, 7.0]
        assert len(_clips(sequence_id, "subtitle")) == 3, "没有画外音的那一拍,屏幕短句照铺"

    @pytest.mark.parametrize("empty", ["hook_line", "call_to_action"])
    def test_出镜版_开场或收尾那句是空的_那一段跳过_其余照样成片(self, monkeypatch, empty: str) -> None:
        ws = _workspace()
        script = {"hook_line": "你家毛衣是不是一洗就起球", "beats": BEATS, "call_to_action": "现在下单", empty: ""}
        studio = Studio(monkeypatch, ws, {"product_pitch_script": script})
        speak_on_camera = studio.video_node("entity_speak")

        def entity_speak(db, scope, config):
            if not str(config.get("text") or "").strip():
                raise WorkflowDomainError("wfErr_emptyText")  # 真节点对空稿子同样当场拒
            return speak_on_camera(db, scope, config)

        monkeypatch.setitem(registry._REGISTRY, "entity_speak", entity_speak)
        graph = product_pitch_short_graph(chat=CHAT, image=SEEDREAM, presenter=True)
        _pick(graph, "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        _pick(graph, "presenter", entity_id="presenter-1")
        context = _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        sequence_id = context["pitch_project"]["sequence_id"]
        video = [clip.timeline_start for clip in _clips(sequence_id, "video")]
        assert [one["text"] for one in studio.calls["entity_speak"]] == [script["hook_line"] or script["call_to_action"]]
        assert video == ([0.0, 3.0, 7.0, 10.0] if empty == "hook_line" else [0.0, 6.0, 9.0, 13.0])
        #: 「其余照样成片」是**导出了**,不只是时间线上铺好了。「配字幕」的控制边此前在规范化时只剩「放收尾」那一条
        #: (来自「逐拍成片」那条被折掉了):收尾那句是空的、「放收尾」跳过时,字幕、导出、交付整段跟着跳过,
        #: 工作流照样报成功 —— 这里此前只看时间线,看不出来。
        assert [one["sequence_id"] for one in studio.calls["export_sequence"]] == [sequence_id]
        assert len(_clips(sequence_id, "subtitle")) == 3, "每拍的字幕照样配上"
        assert context["output"]["output"]["final_asset_id"] == f"export-of-{sequence_id}"

    def test_脚本的目标时长跟着开始参数走_不是写死的一个区间(self, monkeypatch) -> None:
        ws = _workspace()
        captured: list[str] = []
        studio = Studio(monkeypatch, ws, {"product_pitch_script": {"beats": BEATS}})
        answer = studio.llm

        def llm(db, scope, config):
            captured.append(config["system"])
            return answer(db, scope, config)

        monkeypatch.setitem(registry._REGISTRY, "llm", llm)
        graph = _pick(product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id="voice-1"),
                      "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        _run(ws, graph, product_name="羊毛衫", selling_points="不起球", target_duration_seconds=60)
        assert "约 60 秒" in captured[0] and "20-45" not in captured[0]

    def test_出镜版_主播取不到时_脚本那次对话一次都不花(self, monkeypatch) -> None:
        ws = _workspace()
        studio = Studio(monkeypatch, ws, {"product_pitch_script": {"hook_line": "", "beats": BEATS, "call_to_action": ""}})
        graph = product_pitch_short_graph(chat=CHAT, image=SEEDREAM, presenter=True)
        _pick(graph, "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        _pick(graph, "presenter", entity_id="deleted-presenter")

        def gone(db, scope, config):
            raise WorkflowDomainError("wfErr_entityGetNeedsTarget")

        monkeypatch.setitem(registry._REGISTRY, "entity_get", gone)
        with pytest.raises(WorkflowDomainError):
            _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        assert studio.calls["llm"] == []
        with unit_of_work() as db:
            assert db.query(Project).filter(Project.workspace_id == ws).count() == 0

    @pytest.mark.parametrize("missing", ["voice", "image"])
    def test_出镜版_主播没有音色或没有图_写脚本之前就停下_一分钱不花(self, monkeypatch, missing: str) -> None:
        from app.db.models import Notification
        from app.domain.entities.library import create_entity
        from app.domain.workflows.executors.entities import entity_get as real_entity_get

        ws = _workspace()
        voice = make_voice(ws, "主播的嗓子")
        attributes = {"real_person": False, **({} if missing == "voice" else {"voice_engine": "builtin:clone", "voice_id": voice})}
        with unit_of_work() as db:
            entity = create_entity(db, workspace_id=ws, kind="character", name="小美", attributes=attributes)
            db.commit()
            entity_id = entity.id
        studio = Studio(monkeypatch, ws, {"product_pitch_script": {"hook_line": "h", "beats": BEATS, "call_to_action": "c"}})
        #: 取主播用真的节点:音色、图都从资产库里的这个人物来。
        monkeypatch.setitem(registry._REGISTRY, "entity_get", real_entity_get)
        graph = product_pitch_short_graph(chat=CHAT, image=SEEDREAM, presenter=True)
        _pick(graph, "product_photo", asset_id=_asset(ws, "image", "毛衣"))
        _pick(graph, "presenter", entity_id=entity_id)
        _run(ws, graph, product_name="羊毛衫", selling_points="不起球")
        assert studio.calls["llm"] == [] and studio.calls["ai_generate"] == [], "写脚本、出图之前就该停"
        with unit_of_work() as db:
            assert db.query(Project).filter(Project.workspace_id == ws).count() == 0
            titles = [one.title for one in db.query(Notification).filter(Notification.workspace_id == ws)]
        assert any(("音色" if missing == "voice" else "图") in one for one in titles), titles

    def test_出镜版_主播没挑时运行前就拦住(self) -> None:
        graph = product_pitch_short_graph(chat=CHAT, image=SEEDREAM, presenter=True)
        _pick(graph, "product_photo", asset_id="some-photo")
        assert any("presenter" in one for one in validate_graph(graph))

    def test_不出镜版_音色空着运行前就拦住(self) -> None:
        graph = _pick(product_pitch_short_graph(chat=CHAT, image=SEEDREAM, voice_id=""), "product_photo", asset_id="p")
        errors = validate_graph(graph)
        assert any("beat_voice" in one and "voice" in one for one in errors), errors


# --------------------------------------------------------------------------------------
# 商品图 → 模特上身图
# --------------------------------------------------------------------------------------

SCENES = [
    {"scene_label": "通勤", "model_brief": "woman, 28", "setting": "street", "pose": "walking", "image_prompt": "a"},
    {"scene_label": "周末", "model_brief": "woman, 30", "setting": "cafe", "pose": "sitting", "image_prompt": "b"},
]


def _lookbook(*, motion: bool) -> dict[str, Any]:
    scenes = [{**scene, "video_prompt": "turns slowly"} for scene in SCENES] if motion else SCENES
    return {"product_summary": "一件米色针织开衫", "scenes": scenes,
            "copy_markdown": "- 软糯不扎\n- 通勤百搭", "scenes_markdown": "- **通勤**:清晨街头\n- **周末**:咖啡馆"}


class Test上身图真跑:
    @pytest.mark.parametrize("video", [SEEDANCE, VEO], ids=["seedance-2", "veo"])
    def test_带视频_首帧就是上身图_图和视频都进项目_循环交出的是图(self, monkeypatch, video: ModelChoice) -> None:
        ws = _workspace()
        studio = Studio(monkeypatch, ws, {"product_lookbook_plan": _lookbook(motion=True)})
        photo = _asset(ws, "image", "开衫平铺")
        graph = _pick(product_on_model_graph(chat=CHAT, image=SEEDREAM, video=video), "product_photo", asset_id=photo)
        context = _run(ws, graph, product_name="开衫", product_brief="米色针织开衫")

        images = [one for one in studio.calls["ai_generate"] if one["kind"] == "image"]
        clips = [one for one in studio.calls["ai_generate"] if one["kind"] == "video"]
        assert len(images) == len(clips) == 2
        assert all(one["sources"] == [{"asset_id": photo, "role": "reference_image"}] for one in images)
        #: 视频只给首帧 —— 首帧 + 参考图在内置模型上要么互斥、要么不收。
        assert all([source["role"] for source in one["sources"]] == ["first_frame"] for one in clips)

        output = context["output"]["output"]
        project_id = output["project_id"]
        with unit_of_work() as db:
            filed = db.query(Asset).filter(Asset.project_id == project_id).all()
            assert sorted(asset.kind for asset in filed) == ["image", "image", "video", "video"]
            assert set(output["image_asset_ids"]) == {asset.id for asset in filed if asset.kind == "image"}
            assert db.query(Sequence).filter(Sequence.project_id == project_id).count() == 0, "不剪片子,不该建空时间线"
            note = db.get(Note, output["copy_note_id"])
            assert "- 软糯不扎" in note.markdown and "**周末**" in note.markdown
            assert '["' not in note.markdown and '{"' not in note.markdown, "笔记里插的是 JSON 原文"

    def test_模型多规划了几组_也只出开始参数要的那几组(self, monkeypatch) -> None:
        ws = _workspace()
        plan = _lookbook(motion=False)
        plan["scenes"] = plan["scenes"] * 6  # 12 组,开始参数只要 2 组
        studio = Studio(monkeypatch, ws, {"product_lookbook_plan": plan})
        graph = _pick(product_on_model_graph(chat=CHAT, image=SEEDREAM, video=ModelChoice()), "product_photo",
                      asset_id=_asset(ws, "image", "开衫平铺"))
        context = _run(ws, graph, product_name="开衫", product_brief="米色针织开衫", scene_count=2)
        assert len(studio.calls["ai_generate"]) == 2, "「要几组」只写进了提示词,模型多给几组就多付几次钱"
        assert context["shoot_scenes"]["dropped"] == 10

    def test_没有视频模型时只出图(self, monkeypatch) -> None:
        ws = _workspace()
        studio = Studio(monkeypatch, ws, {"product_lookbook_plan": _lookbook(motion=False)})
        graph = _pick(product_on_model_graph(chat=CHAT, image=SEEDREAM, video=ModelChoice()), "product_photo",
                      asset_id=_asset(ws, "image", "开衫平铺"))
        context = _run(ws, graph, product_name="开衫", product_brief="米色针织开衫")
        assert {one["kind"] for one in studio.calls["ai_generate"]} == {"image"}
        assert len(context["output"]["output"]["image_asset_ids"]) == 2


# --------------------------------------------------------------------------------------
# 面料提案、长视频切片、稿子口播
# --------------------------------------------------------------------------------------


class Test面料提案真跑:
    def test_规格页是现成的_Markdown_不是_JSON(self, monkeypatch) -> None:
        ws = _workspace()
        plan = {
            "spec_markdown": "## 规格\n\n- 成分:需与工厂确认",
            "applications": [{"product_type": "窗帘", "why_it_suits": "垂坠", "image_prompt": "curtain"}],
            "applications_markdown": "- **窗帘**:垂坠感好",
            "care_notes": "需与工厂确认",
        }
        studio = Studio(monkeypatch, ws, {"fabric_lookbook_plan": plan})
        graph = _pick(fabric_lookbook_graph(chat=CHAT, image=SEEDREAM), "fabric_photo", asset_id=_asset(ws, "image", "面料"))
        context = _run(ws, graph, fabric_name="亚麻")
        with unit_of_work() as db:
            note = db.get(Note, context["output"]["output"]["spec_note_id"])
            assert "- **窗帘**:垂坠感好" in note.markdown
            assert '"product_type"' not in note.markdown
        #: 没填的参数进提示词时是空的,不是一句「成分,如 60% 棉 40% 亚麻」。
        assert "60%" not in studio.calls["llm"][0]["prompt"]


class Test长视频切片真跑:
    def test_每条一条时间线_都在同一个项目里(self, monkeypatch) -> None:
        ws = _workspace()
        clip = {"title": "第一条", "hook": "", "start_seconds": 10, "end_seconds": 40, "why": "",
                "captions": [{"start": 0, "end": 3, "text": "开场"}]}
        plan = {"clips": [clip, {**clip, "title": "第二条", "start_seconds": 60, "end_seconds": 90}], "skipped_reason": ""}
        Studio(monkeypatch, ws, {"highlight_clips": plan})
        graph = _pick(highlight_shorts_graph(chat=CHAT), "source_video", asset_id=_asset(ws, "video", "访谈", duration=600.0))
        context = _run(ws, graph)
        project_id = context["output"]["output"]["project_id"]
        with unit_of_work() as db:
            assert db.query(Project).filter(Project.workspace_id == ws).count() == 1
            sequences = db.query(Sequence).filter(Sequence.project_id == project_id).all()
            assert sorted(one.name for one in sequences) == ["第一条", "第二条"]
        assert len(context["output"]["output"]["clip_asset_ids"]) == 2


class Test独立的几项_一项失败不拖垮其余:
    def test_切片里有一条起止时间不对_其余照切照导出_通知里说清是哪一条(self, monkeypatch) -> None:
        from app.db.models import Notification

        ws = _workspace()
        good = {"title": "好的", "hook": "", "start_seconds": 10, "end_seconds": 40, "why": "",
                "captions": [{"start": 0, "end": 3, "text": "开场"}]}
        bad = {**good, "title": "原片之外", "start_seconds": 700, "end_seconds": 720}
        studio = Studio(monkeypatch, ws, {"highlight_clips": {"clips": [good, good, bad, good], "skipped_reason": ""}})
        graph = _pick(highlight_shorts_graph(chat=CHAT), "source_video", asset_id=_asset(ws, "video", "访谈", duration=600.0))
        context = _run(ws, graph)
        assert len(studio.calls["export_sequence"]) == 3
        assert context["cut_clips"]["failed"] == [3]
        assert len(context["output"]["output"]["clip_asset_ids"]) == 3
        with unit_of_work() as db:
            body = next(one.body for one in db.query(Notification).filter(Notification.workspace_id == ws)
                        if one.title == "竖屏切片已导出")
        assert "已切出 3 条" in body and "第 3 项没做成" in body

    def test_上身图有一组视频没出来_其余几组的图和视频照样交付归档(self, monkeypatch) -> None:
        ws = _workspace()
        plan = _lookbook(motion=True)
        plan["scenes"] = plan["scenes"] * 2
        studio = Studio(monkeypatch, ws, {"product_lookbook_plan": plan})
        generate = studio.generate
        videos = {"n": 0}

        def flaky(db, scope, config):
            if config["kind"] == "video":
                videos["n"] += 1
                if videos["n"] == 2:
                    raise WorkflowDomainError("wfErr_cancelled")
            return generate(db, scope, config)

        monkeypatch.setitem(registry._REGISTRY, "ai_generate", flaky)
        graph = _pick(product_on_model_graph(chat=CHAT, image=SEEDREAM, video=SEEDANCE), "product_photo",
                      asset_id=_asset(ws, "image", "开衫平铺"))
        context = _run(ws, graph, product_name="开衫", product_brief="米色针织开衫")
        assert len(context["shoot_scenes"]["failed"]) == 1
        assert context["output"]["output"]["scene_count"] == 3
        with unit_of_work() as db:
            filed = db.query(Asset).filter(Asset.project_id == context["output"]["output"]["project_id"]).count()
        assert filed == 4 + 3, "四组的图都归档了,三段视频也归档了"


class Test长视频切片_没挑出片段:
    def test_一条都没挑出来_停下说清楚_不建项目不导出(self, monkeypatch) -> None:
        from app.db.models import Notification

        ws = _workspace()
        studio = Studio(monkeypatch, ws, {"highlight_clips": {"clips": [], "skipped_reason": "全程在念说明书"}})
        graph = _pick(highlight_shorts_graph(chat=CHAT), "source_video", asset_id=_asset(ws, "video", "访谈", duration=600.0))
        _run(ws, graph)
        assert studio.calls["export_sequence"] == []
        with unit_of_work() as db:
            assert db.query(Project).filter(Project.workspace_id == ws).count() == 0, "没切出东西,不该留下一个空项目"
            bodies = [one.body for one in db.query(Notification).filter(Notification.workspace_id == ws)]
        assert any("全程在念说明书" in one for one in bodies)

    def test_转写失败时不留下空项目(self, monkeypatch) -> None:
        ws = _workspace()
        studio = Studio(monkeypatch, ws, {})

        def broken(db, scope, config):
            raise WorkflowDomainError("wfErr_cancelled")

        monkeypatch.setitem(registry._REGISTRY, "transcribe_asset", broken)
        graph = _pick(highlight_shorts_graph(chat=CHAT), "source_video", asset_id=_asset(ws, "video", "访谈", duration=600.0))
        with pytest.raises(WorkflowDomainError):
            _run(ws, graph)
        assert studio.calls["llm"] == []
        with unit_of_work() as db:
            assert db.query(Project).filter(Project.workspace_id == ws).count() == 0


class Test长视频切片_终点超出原片:
    def test_截取夹到原片末尾_字幕也裁到这一条的终点(self, monkeypatch) -> None:
        ws = _workspace()
        clip = {"title": "尾巴", "hook": "", "start_seconds": 590, "end_seconds": 640, "why": "",
                "captions": [{"start": 0, "end": 5, "text": "开头"}, {"start": 8, "end": 15, "text": "跨过终点"},
                             {"start": 40, "end": 50, "text": "原片之外"}]}
        Studio(monkeypatch, ws, {"highlight_clips": {"clips": [clip], "skipped_reason": ""}})
        graph = _pick(highlight_shorts_graph(chat=CHAT), "source_video", asset_id=_asset(ws, "video", "访谈", duration=600.0))
        _run(ws, graph)
        with unit_of_work() as db:
            sequence_id = db.query(Sequence).filter(Sequence.workspace_id == ws).one().id
        assert [_span(one) for one in _clips(sequence_id, "video")] == [10.0]
        assert [(one.timeline_start, one.timeline_start + _span(one), one.text_override)
                for one in _clips(sequence_id, "subtitle")] == [(0.0, 5.0, "开头"), (8.0, 10.0, "跨过终点")]


class Test稿子口播真跑:
    def test_稿子和音色写在分段配音上_逐段说话接上时间线(self, monkeypatch) -> None:
        ws = _workspace()
        studio = Studio(monkeypatch, ws, {})
        graph = talking_script_video_graph(voice_id="voice-1")
        _pick(graph, "face", asset_id=_asset(ws, "image", "正脸"))
        _pick(graph, "voicing", text="大家好,今天聊聊面料。")
        speak_loop = next(one for one in graph["nodes"] if one["id"] == "speak_segments")
        next(one for one in speak_loop["config"]["body"]["nodes"] if one["id"] == "speak")["config"]["consent"] = "yes"
        context = _run(ws, graph)
        assert studio.calls["talking_segments"][0]["voice"] == "voice-1"
        assert studio.calls["talking_segments"][0]["text"] == "大家好,今天聊聊面料。"
        assert len(studio.calls["image_speak"]) == 2
        video = _clips(context["project"]["sequence_id"], "video")
        assert [clip.timeline_start for clip in video] == [0.0, 6.0]

    def test_稿子或音色空着运行前就拦住(self) -> None:
        graph = talking_script_video_graph(voice_id="")
        errors = validate_graph(graph)
        assert any("voicing" in one and "text" in one for one in errors), errors
        assert any("voicing" in one and "voice" in one for one in errors), errors


# --------------------------------------------------------------------------------------
# 从主题到完整视频
# --------------------------------------------------------------------------------------


def _sample(schema: dict[str, Any]) -> Any:
    """按 JSON Schema 造一份最小的合法回答;要紧的字段由测试自己覆盖。"""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        return {key: _sample(value) for key, value in (schema.get("properties") or {}).items()}
    if kind == "array":
        return [_sample(schema["items"]) for _ in range(max(1, int(schema.get("minItems") or 1)))]
    if kind in ("number", "integer"):
        if "exclusiveMinimum" in schema:
            return schema["exclusiveMinimum"] + 1
        return schema.get("minimum", 1)
    if kind == "boolean":
        return False
    pattern = schema.get("pattern")
    if not pattern:
        return "x"
    return next(one for one in ("a", "#20242c") if re.search(pattern, one))


class Test整片真跑:
    def test_角色有的沿用没有的画_每一镜三种走法都交得出_有口播的镜头配音配字幕(self, monkeypatch, tmp_path) -> None:
        ws = _workspace()
        #: 工作区里收着一件真道具。「可用的 3D 道具」用真执行器(读 GLB 量尺寸),不打桩 —— 此前它在模板顶层没有
        #: 入边,引擎根本不跑它,布景师拿到的清单永远是空的;这里的假节点又恰好交空清单,两边一起把它盖住了。
        _import_glb(ws, "产品主体", tmp_path, width=2, height=1, depth=3)
        graph = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=SEEDANCE)
        schemas = {
            node["config"]["json_schema_name"]: node["config"]["json_schema"]
            for node in graph["nodes"] if node["type"] == "llm"
        }
        bible = _sample(schemas["professional_video_visual_bible"])
        character = bible["characters"][0]
        bible["characters"] = [{**character, "id": "zhou", "name": "老周"}, {**character, "id": "lin", "name": "小林"}]
        storyboard = _sample(schemas["professional_timed_storyboard"])
        shot = storyboard["shots"][0]
        storyboard["shots"] = [
            #: 走首帧,还要尾帧;有口播。
            {**shot, "shot_number": 1, "reference_mode": "keyframes", "last_frame_prompt": "ends on a close-up",
             "narration": "第一镜的口播", "generation_prompt": "p1"},
            #: 走首帧,不要尾帧;没有口播。
            {**shot, "shot_number": 2, "reference_mode": "keyframes", "last_frame_prompt": "", "narration": "",
             "generation_prompt": "p2"},
            #: 走参考;有口播。
            {**shot, "shot_number": 3, "reference_mode": "references", "last_frame_prompt": "", "narration": "第三镜",
             "generation_prompt": "p3"},
        ]
        plans = {name: _sample(schema) for name, schema in schemas.items()}
        plans.update({"professional_video_visual_bible": bible, "professional_timed_storyboard": storyboard})
        studio = Studio(monkeypatch, ws, plans)
        library = _asset(ws, "image", "老周三视图")
        saved: list[dict[str, Any]] = []

        def entity_get(db, scope, config):
            known = config.get("name") == "老周"
            return {"entity_id": "e-zhou" if known else "", "found": int(known), "name": config.get("name"),
                    "description": "", "prompt": "", "asset_ids": [library] if known else [], "asset_id": "",
                    "voice_engine": "", "voice_id": ""}

        def entity_save(db, scope, config):
            saved.append(config)
            return {"entity_id": "e", "created": 1, "added": 1, "name": ""}

        def scene_render(db, scope, config):
            shot_id = config["shot_id"]
            return {"first_frame_asset_id": f"blockout-first-{shot_id}", "last_frame_asset_id": f"blockout-last-{shot_id}",
                    "video_asset_id": f"blockout-move-{shot_id}", "camera_move": "static", "skipped_models": 0}

        fakes = {
            "entity_get": entity_get,
            "entity_list": lambda db, scope, config: {"entities": [], "count": 0, "text": ""},
            "entity_save": entity_save,
            "scene_create": lambda db, scope, config: {"scene_id": "scene-1", "shot_ids": [], "shot_count": 3},
            "scene_render": scene_render,
        }
        for node_type, handler in fakes.items():
            monkeypatch.setitem(registry._REGISTRY, node_type, handler)

        context = _run(ws, graph, topic="一家老面馆", voice_id="voice-1")

        #: 道具清单真的列出来了,而且交到了设计布景的那一次对话里。
        assert context["props"]["count"] == 1
        set_design = next(one for one in studio.calls["llm"] if one["name"] == "blockout_scene")
        assert "产品主体 · 宽 2.00 × 高 1.00 × 深 3.00 米" in set_design["prompt"], set_design["prompt"]
        #: 老周库里有图,不再画;小林没有,画一张三视图并存进资产库。场景同样是新的。
        sheets = [one for one in studio.calls["ai_generate"] if one["prompt"].startswith("Character turnaround")]
        assert len(sheets) == 1 and "小林" in sheets[0]["prompt"]
        assert sorted(one["kind"] for one in saved) == ["character", "location"]
        assert context["character_sheets"]["results"][0] == f"{library}:reference_image"

        clips = sorted((one for one in studio.calls["ai_generate"] if one["kind"] == "video"), key=lambda one: one["prompt"])
        roles = [sorted({source["role"] for source in one["sources"]}) for one in clips]
        assert roles == [["first_frame", "last_frame"], ["first_frame"], ["reference_image", "reference_video"]]
        references = [source for source in clips[2]["sources"] if source["role"] == "reference_image"]
        assert len(references) == 4, "两张三视图 + 一张设定图 + 白模帧"

        sequence_id = context["video_project"]["sequence_id"]
        assert [clip.timeline_start for clip in _clips(sequence_id, "video")] == [0.0, 5.0, 10.0]
        assert [clip.timeline_start for clip in _clips(sequence_id, "audio")] == [0.0, 10.0]
        assert [(clip.timeline_start, clip.text_override) for clip in _clips(sequence_id, "subtitle")] == [
            (0.0, "第一镜的口播"), (10.0, "第三镜")]
        assert context["output"]["output"]["final_asset_id"] == f"export-of-{sequence_id}"
        #: 新画的三视图、设定图和每一镜的关键帧都归进成片项目(库里认出来的那张不动)。
        with unit_of_work() as db:
            filed = {asset.name for asset in db.query(Asset).filter(Asset.project_id == context["video_project"]["project_id"])}
        assert {"镜头 1 · 关键帧 1", "镜头 1 · 关键帧 2", "镜头 2 · 关键帧"} <= filed
        assert library not in {asset.id for asset in _assets_in_project(context["video_project"]["project_id"])}
        assert len([one for one in _assets_in_project(context["video_project"]["project_id"]) if one.name == "gen-image"]) == 2


def _assets_in_project(project_id: str) -> list[Asset]:
    with unit_of_work() as db:
        assets = db.query(Asset).filter(Asset.project_id == project_id).all()
        for asset in assets:
            db.expunge(asset)
        return assets


# --------------------------------------------------------------------------------------
# 克隆引擎跑不起来:预填音色和前置检查同一个判据,运行前就拦
# --------------------------------------------------------------------------------------


def _clone_engine(monkeypatch, *, ready: bool) -> None:
    """克隆引擎的探测结果(真机上要起子进程 import torch):已知跑得起来 / 已知跑不起来。"""
    from app.ai.runtime import tts_models

    monkeypatch.setattr(tts_models, "runtime_status", lambda engine: (ready, True))
    monkeypatch.setattr(tts_models, "is_installed", lambda engine: True)


def _template_client() -> tuple[Any, str]:
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _template_workflow(client: Any, ws: str, template_id: str) -> dict[str, Any]:
    response = client.post("/api/workflows", json={"workspace_id": ws, "name": template_id, "template_id": template_id})
    assert response.status_code == 200, response.text
    return response.json()


def _voices_in(graph: dict[str, Any]) -> list[str]:
    """图里(连同循环体)所有填了音色的地方:开始参数 voice_id、配音节点的 voice。"""
    found: list[str] = []
    for node in graph["nodes"]:
        config = node.get("config") or {}
        if node["type"] == "start":
            found.append(str((config.get("params") or {}).get("voice_id", "")))
        if "voice" in config and "{{" not in str(config["voice"]):
            found.append(str(config["voice"]))
        if isinstance(config.get("body"), dict):
            found += _voices_in(config["body"])
    return [one for one in found if one]


class Test克隆引擎没装:
    @pytest.mark.parametrize("template_id", ["full_video_generation", "footage_montage", "translated_dub",
                                             "product_pitch_short"])
    def test_前置检查说缺_建出来的图里也不填音色(self, monkeypatch, template_id: str) -> None:
        from app.core.db import SessionLocal
        from app.domain.workflows.templates import requirement_statuses
        from tests.util import make_voice, user_id

        client, ws = _template_client()
        make_voice(ws, "嗓子")
        _clone_engine(monkeypatch, ready=False)
        with SessionLocal() as db:
            assert requirement_statuses(db, user_id=user_id(), workspace_id=ws)["cloned_voice"] == "missing"
        assert _voices_in(_template_workflow(client, ws, template_id)["graph"]) == [], "卡片上说缺,图里却填着音色"

    def test_引擎跑得起来时照旧预填(self, monkeypatch) -> None:
        from tests.util import make_voice

        client, ws = _template_client()
        voice = make_voice(ws, "嗓子")
        _clone_engine(monkeypatch, ready=True)
        assert _voices_in(_template_workflow(client, ws, "footage_montage")["graph"]) == [voice]

    def test_开始参数里填了音色而引擎跑不起来_运行前就拦_一次对话都不花(self, monkeypatch) -> None:
        """音色是开始参数经循环的 inputs 转进「念旁白」的 —— 运行前检查要认得这条路,不只看字面量。"""
        from sqlalchemy import select

        from app.core.db import SessionLocal
        from app.db.models import Job
        from app.domain.workflows import create_workflow
        from app.domain.workflows.engine import start_workflow_job
        from tests.util import make_voice, user_id

        ws = _workspace()
        voice = make_voice(ws, "嗓子")
        _clone_engine(monkeypatch, ready=False)
        graph = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=SEEDANCE)
        with SessionLocal() as db:
            workflow = create_workflow(db, workspace_id=ws, name="整片", graph=graph, created_by=user_id())
            db.commit()
            with pytest.raises(WorkflowDomainError) as refused:
                start_workflow_job(db, workflow, created_by=user_id(), params={"topic": "面馆", "voice_id": voice})
            assert refused.value.key == "voiceErr_noRuntime"
            assert list(db.scalars(select(Job).where(Job.workspace_id == ws))) == [], "一个节点都没排"


class Test整片改画幅:
    def test_视频模型不收这个画幅_运行前就拦_一个节点都不排(self) -> None:
        """Veo 只收 16:9 / 9:16。此前改成 1:1 要等五次对话、三视图和关键帧都付完钱,生成视频那一步才被拒。"""
        from sqlalchemy import select

        from app.core.db import SessionLocal
        from app.db.models import Job
        from app.domain.generation.operations import GenerationDomainError
        from app.domain.workflows import create_workflow
        from app.domain.workflows.engine import start_workflow_job
        from tests.util import add_provider, user_id

        ws = _workspace()
        with SessionLocal() as db:
            #: 真的一条 Veo 连接:运行前检查按跑的人解析模型,和执行时漏斗同一种解析。
            profile = add_provider(db, name="Google", vendor="google", api_key="k", model="veo", capability_ids=["video"])
            db.commit()
            veo = ModelChoice(profile_id=profile.id, provider="google", model="veo")
        graph = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=veo)
        with SessionLocal() as db:
            workflow = create_workflow(db, workspace_id=ws, name="整片", graph=graph, created_by=user_id())
            db.commit()
            with pytest.raises((WorkflowDomainError, GenerationDomainError)) as refused:
                start_workflow_job(db, workflow, created_by=user_id(), params={"topic": "面馆", "aspect_ratio": "1:1"})
            assert refused.value.key == "genErr_choiceOnly"
            assert list(db.scalars(select(Job).where(Job.workspace_id == ws))) == []
            #: 它收的画幅照常放行。
            start_workflow_job(db, workflow, created_by=user_id(), params={"topic": "面馆", "aspect_ratio": "9:16"})

    def test_对话节点连接模型都留空_跑的人又没有对话模型_运行前就拦(self) -> None:
        """整片建图时这台机器上还没配对话模型:五次对话都留空,此前照样能按下运行,轮到第一次对话才失败。"""
        from sqlalchemy import select

        from app.core.db import SessionLocal
        from app.db.models import Job
        from app.domain.workflows import create_workflow
        from app.domain.workflows.engine import start_workflow_job
        from tests.util import add_provider, user_id

        ws = _workspace()
        graph = full_video_generation_graph(chat=ModelChoice(), image=SEEDREAM, video=SEEDANCE)
        with SessionLocal() as db:
            workflow = create_workflow(db, workspace_id=ws, name="整片", graph=graph, created_by=user_id())
            db.commit()
            with pytest.raises(WorkflowDomainError) as refused:
                start_workflow_job(db, workflow, created_by=user_id(), params={"topic": "面馆"})
            assert refused.value.key == "wfErr_llmNoChatConnection"
            assert list(db.scalars(select(Job).where(Job.workspace_id == ws))) == []
            #: 配上一条会对话的连接,留空的节点就用它 —— 不再拦。
            add_provider(db, name="P", vendor="openai", base_url="https://example.test/v1", api_key="k",
                         model="chat-model", capability_ids=["chat"])
            db.commit()
            start_workflow_job(db, workflow, created_by=user_id(), params={"topic": "面馆"})

