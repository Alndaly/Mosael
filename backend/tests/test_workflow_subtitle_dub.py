"""「翻译配音」那条链路:逐字稿 → 逐句译文 → 字幕 → 配音,配音变速压回原段落长度。

**这条链路此前缺的不是能力,是入口。** 字幕配音(domain/voices/subtitle_dub)一直在,
但只有剪辑台上那一个按钮够得着它:工作流画布上没有节点,对话里没有工具。于是"把这个视频
翻译配音"这件很常见的事,只能人坐在剪辑台前一步步点。

这里钉的是这条链路上**容易悄悄错掉**的几处:时间码从哪来、条数对不上怎么办、
「压回原长度」默认开不开。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Clip, Track, Workflow
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _setup() -> tuple[str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}
    ).json()
    return ws, sequence["id"]


def _run(node: str, ws: str, config: dict) -> dict:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        handler = get_executor(node)
        assert handler is not None, f"{node} 没有执行器"
        return handler(db, workflow, config)


SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "こんにちは", "speaker": "", "tokens": []},
    {"start": 2.5, "end": 5.0, "text": "元気ですか", "speaker": "", "tokens": []},
]


def _cues(sequence_id: str) -> list[tuple[str, float, float]]:
    with SessionLocal() as db:
        track = (
            db.query(Track)
            .filter(Track.sequence_id == sequence_id, Track.kind == "subtitle")
            .first()
        )
        if track is None:
            return []
        clips = db.query(Clip).filter(Clip.track_id == track.id).all()
        return sorted(
            (clip.text_override or "", clip.timeline_start, clip.src_out - clip.src_in)
            for clip in clips
        )


class Test生成字幕:
    def test_没有字幕轨就建一条(self) -> None:
        """新建的时间线只有视频轨和音频轨。逼用户先接一个「加轨道」节点,只是把机器能算的事推给人。"""
        ws, sequence_id = _setup()
        out = _run("generate_subtitles", ws, {"sequence_id": sequence_id, "segments": SEGMENTS})
        assert out["count"] == 2
        assert _cues(sequence_id) == [("こんにちは", 0.0, 2.0), ("元気ですか", 2.5, 2.5)]

    def test_有译文就铺译文_时间码仍来自原段落(self) -> None:
        """**这是整条链路的关键一步。** 译文的句子长度和原文不一样,如果时间码跟着译文走,
        从第一句起就会错位;时间码只能来自原始段落。"""
        ws, sequence_id = _setup()
        _run("generate_subtitles", ws, {
            "sequence_id": sequence_id,
            "segments": SEGMENTS,
            "texts": ["你好", "你还好吗"],
        })
        assert _cues(sequence_id) == [("你好", 0.0, 2.0), ("你还好吗", 2.5, 2.5)]

    def test_条数对不上要报错_不能截断(self) -> None:
        """少一条就意味着从那一条起每句都配错了时间,而截断后的成片看起来是完整的 ——
        那种错要有人从头看一遍才发现。"""
        ws, sequence_id = _setup()
        with pytest.raises(WorkflowDomainError, match="对不上"):
            _run("generate_subtitles", ws, {
                "sequence_id": sequence_id,
                "segments": SEGMENTS,
                "texts": ["你好"],
            })

    def test_双语字幕原文在上译文在下(self) -> None:
        ws, sequence_id = _setup()
        _run("generate_subtitles", ws, {
            "sequence_id": sequence_id,
            "segments": SEGMENTS,
            "texts": ["你好", "你还好吗"],
            "keep_original": "yes",
        })
        assert _cues(sequence_id)[0][0] == "こんにちは\n你好"

    def test_素材不在零秒时字幕整体平移(self) -> None:
        """逐字稿的时间是**素材内**的时间。视频接在第几秒由 timeline_append 说了算。"""
        ws, sequence_id = _setup()
        _run("generate_subtitles", ws, {
            "sequence_id": sequence_id, "segments": SEGMENTS, "offset": 10,
        })
        assert [start for _, start, _ in _cues(sequence_id)] == [10.0, 12.5]

    def test_接住一串_JSON(self) -> None:
        """手填时 segments 只能是文本;上游给对象时 interpolate 会保留原类型,两种都要认。"""
        import json

        ws, sequence_id = _setup()
        out = _run("generate_subtitles", ws, {
            "sequence_id": sequence_id, "segments": json.dumps(SEGMENTS, ensure_ascii=False),
        })
        assert out["count"] == 2

    def test_译文不按逗号拆(self) -> None:
        """句子里全是逗号。按逗号拆会把一句话拆成五句,然后条数对不上 —— 或者更糟,正好对上。"""
        ws, sequence_id = _setup()
        _run("generate_subtitles", ws, {
            "sequence_id": sequence_id,
            "segments": SEGMENTS,
            "texts": ["你好，很高兴见到你", "你还好吗，最近忙不忙"],
        })
        assert _cues(sequence_id)[0][0] == "你好，很高兴见到你"


class Test字幕配音:
    def test_压回原段落长度默认是开着的(self) -> None:
        """节点声明里的 default 只用于表单预选,不会写进 config —— 执行体得自己兜住那一档,
        否则"默认开"的选项对每一条没动过它的工作流都是关的,而那正是这条工作流的要点。"""
        seen: dict = {}

        def fake_start(db, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("到此为止:要看的是传下去的参数")

        import app.domain.voices.subtitle_dub as dub

        ws, sequence_id = _setup()
        original = dub.start_subtitle_dub
        dub.start_subtitle_dub = fake_start
        try:
            with pytest.raises(RuntimeError):
                _run("dub_subtitles", ws, {
                    "sequence_id": sequence_id, "clip_ids": ["c1"], "voice_id": "v1",
                })
        finally:
            dub.start_subtitle_dub = original
        assert seen["match_duration"] is True

    def test_明确关掉时就是关的(self) -> None:
        seen: dict = {}

        def fake_start(db, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop")

        import app.domain.voices.subtitle_dub as dub

        ws, sequence_id = _setup()
        original = dub.start_subtitle_dub
        dub.start_subtitle_dub = fake_start
        try:
            with pytest.raises(RuntimeError):
                _run("dub_subtitles", ws, {
                    "sequence_id": sequence_id, "clip_ids": ["c1"], "voice_id": "v1",
                    "match_duration": "no",
                })
        finally:
            dub.start_subtitle_dub = original
        assert seen["match_duration"] is False

    def test_两条路都没选时说清有哪两条(self) -> None:
        ws, sequence_id = _setup()
        with pytest.raises(WorkflowDomainError, match="克隆音色"):
            _run("dub_subtitles", ws, {"sequence_id": sequence_id, "clip_ids": ["c1"]})

    def test_别的工作区的时间线配不了(self) -> None:
        _, other_sequence = _setup()
        ws, _ = _setup()
        with pytest.raises(WorkflowDomainError, match="工作区"):
            _run("dub_subtitles", ws, {
                "sequence_id": other_sequence, "clip_ids": ["c1"], "voice_id": "v1",
            })


class Test官方工作流:
    def test_译配模板连得起来且默认压回原长度(self) -> None:
        from app.domain.workflows import validate_graph
        from app.domain.workflows.templates import translated_dub_graph

        graph = translated_dub_graph(voice_id="v1")
        # 只差用户自己选那份视频 —— 其余每一处配置都该是完整的。
        assert validate_graph(graph) == ["节点 source_video 缺少必填配置 asset_id"]
        nodes = {node["id"]: node for node in graph["nodes"]}
        assert nodes["dubbing"]["config"]["match_duration"] == "yes"
        # 字幕的时间码来自逐字稿,落点来自视频真正接到了第几秒。模板写的是 {{引用}},
        # canonicalize_data_bindings 会把它规范成真的数据边 —— 画布上看得见这几条连线。
        wired = {
            (edge["source"], edge["source_output"], edge["target_input"])
            for edge in graph["edges"]
            if edge.get("kind") == "data" and edge["target"] == "translated_subtitles"
        }
        assert ("verbatim_transcript", "segments", "segments") in wired
        assert ("translate_lines", "results", "texts") in wired
        assert ("video_on_timeline", "timeline_start", "offset") in wired
        # 逐句翻译:循环体每次只交出一句译文,而不是整个子作用域。
        assert nodes["translate_lines"]["config"]["output"] == "{{translate_line.text}}"
        assert {
            (edge["source"], edge["source_output"], edge["target_input"])
            for edge in graph["edges"]
            if edge.get("kind") == "data" and edge["target"] == "translate_lines"
        } == {("verbatim_transcript", "segments", "items")}
        body = nodes["translate_lines"]["config"]["body"]
        assert body["nodes"][0]["config"]["text"] == "{{loop.item.text}}"

    def test_新节点都归了类(self) -> None:
        """EXTERNAL/INTERNAL 合起来必须覆盖全部节点 —— 漏掉的那个恰恰是没人想过后果的那个。"""
        from app.domain.workflows import EXTERNAL_NODE_TYPES, INTERNAL_NODE_TYPES

        for node_type in ("generate_subtitles", "dub_subtitles"):
            assert node_type in EXTERNAL_NODE_TYPES | INTERNAL_NODE_TYPES
            assert node_type in NODE_TYPES
