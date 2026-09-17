"""遍历循环可以并发;整片生成把「生成」和「上时间线」拆开,并给口播配字幕。

钉住的是:

1. 并发时**结果仍按原顺序**,而且真的是同时跑的;失败照样 fail-fast,报序号最小的那项;
   并发数有上限;不写 output 时每项结果带着它自己那一项(`loop`)。
2. 「生成字幕」能从任意对象列表里按字段路径取起止和文本;允许为空时交出 0 条、不建空轨。
3. 用**模板里真实的**三个节点(并发生成 → 按序上时间线 → 口播字幕)跑一遍,只把视频生成和
   语音合成换成假的:画面按镜头顺序接上,口播落在各自镜头的起点,没有口播的镜头不出字幕。
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Track, Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows import executors as registry
from app.domain.workflows.executors import get_executor
from app.domain.workflows.executors.loops import LOOP_FOREACH_MAX_CONCURRENCY
from tests.util import fresh_client


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _workflow(ws: str) -> Workflow:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        db.expunge(workflow)
        return workflow


def _loop(ws: str, config: dict[str, Any]) -> dict[str, Any]:
    with SessionLocal() as db:
        workflow = db.get(Workflow, _workflow(ws).id)
        return get_executor("loop_foreach")(db, workflow, config)


@pytest.fixture
def fake_node(monkeypatch):
    """临时换掉某个节点类型的执行器。"""

    def install(node_type: str, handler) -> None:
        monkeypatch.setitem(registry._REGISTRY, node_type, handler)

    return install


class Test循环并发:
    def test_同时跑_结果仍按原顺序(self, fake_node) -> None:
        ws = _workspace()
        running = 0
        peak = 0
        lock = threading.Lock()

        def slow_echo(db, workflow, config):
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            # 越靠前的越慢:顺序执行和"谁先完成谁在前"都会排错。
            time.sleep(0.05 * (5 - int(config["index"])))
            with lock:
                running -= 1
            return {"text": config["item"]}

        fake_node("template", slow_echo)
        body = {"nodes": [{"id": "echo", "type": "template", "config": {"template": "x", "item": "{{loop.item}}", "index": "{{loop.index}}"}}], "edges": []}
        out = _loop(ws, {"items": ["a", "b", "c", "d", "e"], "body": body, "output": "{{echo.text}}", "concurrency": 3})
        assert out["results"] == ["a", "b", "c", "d", "e"]
        assert peak == 3, f"没有真的同时跑(峰值 {peak})"

    def test_失败时报序号最小的那项(self, fake_node) -> None:
        ws = _workspace()

        def boom(db, workflow, config):
            if config["item"] in {"c", "e"}:
                time.sleep(0.02 if config["item"] == "c" else 0)
                raise WorkflowDomainError(f"炸在 {config['item']}")
            return {"text": config["item"]}

        fake_node("template", boom)
        body = {"nodes": [{"id": "echo", "type": "template", "config": {"template": "x", "item": "{{loop.item}}"}}], "edges": []}
        with pytest.raises(WorkflowDomainError) as caught:
            _loop(ws, {"items": ["a", "b", "c", "d", "e"], "body": body, "concurrency": 4})
        assert "第 3/5 次迭代" in str(caught.value) and "炸在 c" in str(caught.value)

    def test_并发数有上限_写错就说(self, fake_node) -> None:
        ws = _workspace()
        seen: set[int] = set()
        lock = threading.Lock()
        active = 0

        def track(db, workflow, config):
            nonlocal active
            with lock:
                active += 1
                seen.add(active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return {"text": ""}

        fake_node("template", track)
        body = {"nodes": [{"id": "echo", "type": "template", "config": {"template": "x"}}], "edges": []}
        _loop(ws, {"items": list(range(12)), "body": body, "concurrency": 50})
        assert max(seen) <= LOOP_FOREACH_MAX_CONCURRENCY
        with pytest.raises(WorkflowDomainError, match="整数"):
            _loop(ws, {"items": [1], "body": body, "concurrency": "很多"})

    def test_不写output时每项带着它自己那一项(self, fake_node) -> None:
        ws = _workspace()
        fake_node("template", lambda db, workflow, config: {"text": "ok"})
        body = {"nodes": [{"id": "echo", "type": "template", "config": {"template": "x"}}], "edges": []}
        out = _loop(ws, {"items": [{"n": 1}], "body": body, "inputs": {"shared": "x"}})
        result = out["results"][0]
        assert result["loop"] == {"item": {"n": 1}, "index": 0}
        assert result["echo"] == {"text": "ok"}
        assert "input" not in result, "共享输入每项都一样,不该重复带"


def _sequence(ws: str) -> tuple[str, str, str]:
    """一条和整片生成里一样的新时间线(视频轨 + 音频轨),用的就是那个节点。"""
    with SessionLocal() as db:
        workflow = db.get(Workflow, _workflow(ws).id)
        made = get_executor("project_sequence_create")(db, workflow, {"name": "成片", "width": 1280, "height": 720, "fps": 30})
    return made["sequence_id"], made["video_track_id"], made["audio_track_id"]


def _asset(ws: str, kind: str, duration: float, name: str) -> str:
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind=kind, name=name, source="generated", file_key=f"k-{name}", media_info={"duration": duration})
        db.add(asset)
        db.commit()
        return asset.id


class Test按字段取字幕:
    def test_嵌套字段与跳过空段(self) -> None:
        ws = _workspace()
        sequence_id, _, _ = _sequence(ws)
        segments = [
            {"placed": {"timeline_start": 0, "timeline_end": 2.5}, "caption": {"text": "第一句"}},
            {"placed": "", "caption": {"text": "这一镜没有口播"}},
            {"placed": {"timeline_start": 5, "timeline_end": 7}, "caption": {"text": "第二句"}},
        ]
        with SessionLocal() as db:
            out = get_executor("generate_subtitles")(db, db.get(Workflow, _workflow(ws).id), {
                "sequence_id": sequence_id, "segments": segments,
                "start_field": "placed.timeline_start", "end_field": "placed.timeline_end", "text_field": "caption.text",
            })
        assert out["count"] == 2
        with SessionLocal() as db:
            clips = sorted(db.query(Clip).filter(Clip.id.in_(out["clip_ids"])).all(), key=lambda c: c.timeline_start)
            assert [(c.timeline_start, c.text_override) for c in clips] == [(0.0, "第一句"), (5.0, "第二句")]

    def test_允许为空时交出0条_不建空轨(self) -> None:
        ws = _workspace()
        sequence_id, _, _ = _sequence(ws)
        with SessionLocal() as db:
            tracks_before = db.query(Track).filter(Track.sequence_id == sequence_id).count()
            out = get_executor("generate_subtitles")(db, db.get(Workflow, _workflow(ws).id), {
                "sequence_id": sequence_id, "segments": [{"start": "", "end": "", "text": ""}], "allow_empty": "yes",
            })
            assert out["count"] == 0 and out["track_id"] == ""
            assert db.query(Track).filter(Track.sequence_id == sequence_id).count() == tracks_before
            with pytest.raises(WorkflowDomainError, match="没有一条"):
                get_executor("generate_subtitles")(db, db.get(Workflow, _workflow(ws).id), {
                    "sequence_id": sequence_id, "segments": [{"start": "", "end": "", "text": ""}],
                })


def _middle_of_full_video(fake_node, *, shots, voice_id, project) -> tuple[dict[str, Any], bool]:
    """跑模板里真实的「并发生成 → 按序上时间线 → 口播字幕」三个节点。

    它们的上游(分镜、成片项目、开始节点)换成直接交出固定值的假节点 —— 边照原样留着,
    所以模板里被规范成数据边的那些引用,走的是和真跑一样的路。
    """
    from app.domain.workflows.engine import execute_graph
    from app.domain.workflows.templates import ModelChoice, full_video_generation_graph

    graph = full_video_generation_graph(
        chat=ModelChoice(profile_id="c", provider="o", model="m"),
        video=ModelChoice(profile_id="v", provider="f", model="vm"),
    )
    wanted = {"generate_shots", "assemble_timeline", "narration_subtitles"}
    fixtures = {
        "storyboard": {"json": {"shots": shots}},
        "video_project": project,
        "start": {"voice_id": voice_id},
    }
    #: 假节点用 `code` 类型 —— 这三个节点的循环体里都没有它,换掉不会波及被测的部分。
    fake_node("code", lambda db, workflow, config: fixtures[config["fixture"]])
    nodes = [{"id": key, "type": "code", "config": {"fixture": key}} for key in fixtures]
    nodes += [node for node in graph["nodes"] if node["id"] in wanted]
    edges = [edge for edge in graph["edges"] if edge["target"] in wanted and edge["source"] in wanted | set(fixtures)]
    workflow = _workflow(project["workspace_id"])
    return execute_graph({"nodes": nodes, "edges": edges}, wf_id=workflow.id, entry_is_root=True)


def _assemble_seconds() -> float:
    """每镜多长由模板按视频模型定;从模板里读,不在测试里另写一个数。"""
    from app.domain.workflows.templates import ModelChoice, full_video_generation_graph

    graph = full_video_generation_graph(chat=ModelChoice(), video=ModelChoice(profile_id="v", provider="f", model="vm"))
    assemble = next(node for node in graph["nodes"] if node["id"] == "assemble_timeline")
    return float(assemble["config"]["body"]["nodes"][0]["config"]["end"])


class Test整片生成的中段:
    def test_并发生成_按序上时间线_口播对齐并配字幕(self, fake_node) -> None:
        ws = _workspace()
        sequence_id, video_track, audio_track = _sequence(ws)
        seconds = _assemble_seconds()

        shots = [
            {"shot_number": 1, "generation_prompt": "p1", "negative_prompt": "", "narration": "第一镜的口播"},
            {"shot_number": 2, "generation_prompt": "p2", "negative_prompt": "", "narration": ""},
            {"shot_number": 3, "generation_prompt": "p3", "negative_prompt": "", "narration": "第三镜的口播,比较长"},
        ]
        # 口播时长各不相同:第一段比镜头短,第三段比镜头长 —— 正是会让旧版错位的那种。
        narration_seconds = {"第一镜的口播": seconds * 0.5, "第三镜的口播,比较长": seconds * 1.2}

        def fake_generate(db, workflow, config):
            time.sleep(0.02)
            return {"asset_id": _asset(ws, "video", 20.0, config["prompt"])}

        def fake_speech(db, workflow, config):
            return {"asset_id": _asset(ws, "audio", narration_seconds[config["text"]], config["text"])}

        fake_node("ai_generate", fake_generate)
        fake_node("asset_update", lambda db, workflow, config: {"asset_ids": [config["asset_ids"]]})
        fake_node("synthesize_speech", fake_speech)

        context, cancelled = _middle_of_full_video(
            fake_node,
            shots=shots,
            voice_id="voice-1",
            project={"workspace_id": ws, "project_id": "", "sequence_id": sequence_id,
                     "video_track_id": video_track, "audio_track_id": audio_track},
        )
        assert not cancelled
        assert context["narration_subtitles"]["count"] == 2, "没有口播的镜头不该出字幕"

        with SessionLocal() as db:
            video = sorted(db.query(Clip).filter(Clip.track_id == video_track).all(), key=lambda c: c.timeline_start)
            names = [db.get(Asset, clip.asset_id).name for clip in video]
            assert names == ["p1", "p2", "p3"], "并发生成之后,上时间线仍要按镜头顺序"
            assert [clip.timeline_start for clip in video] == [0.0, seconds, seconds * 2]

            audio = sorted(db.query(Clip).filter(Clip.track_id == audio_track).all(), key=lambda c: c.timeline_start)
            #: 第三段口播落在**第三镜的起点**,而不是接在第一段口播(只有半镜长)后面。
            assert [clip.timeline_start for clip in audio] == [0.0, seconds * 2]
            #: 比镜头长的那段被加速塞进了镜头。
            assert audio[1].speed == pytest.approx(1.2)

            subtitle_ids = context["narration_subtitles"]["clip_ids"]
            subtitles = sorted(db.query(Clip).filter(Clip.id.in_(subtitle_ids)).all(), key=lambda c: c.timeline_start)
            assert [(c.timeline_start, c.text_override) for c in subtitles] == [
                (0.0, "第一镜的口播"),
                (seconds * 2, "第三镜的口播,比较长"),
            ]
            #: 字幕时长跟着口播**实际**的长度(加速后正好一镜)。
            assert (subtitles[1].src_out - subtitles[1].src_in) == pytest.approx(seconds)

    def test_没选音色时整片照样生成完(self, fake_node) -> None:
        ws = _workspace()
        sequence_id, video_track, audio_track = _sequence(ws)
        fake_node("ai_generate", lambda db, workflow, config: {"asset_id": _asset(ws, "video", 20.0, config["prompt"])})
        fake_node("asset_update", lambda db, workflow, config: {})

        def no_speech(db, workflow, config):
            raise AssertionError("没选音色时不该去合成")

        fake_node("synthesize_speech", no_speech)
        context, cancelled = _middle_of_full_video(
            fake_node,
            shots=[{"shot_number": 1, "generation_prompt": "p", "negative_prompt": "", "narration": "有字但没声音"}],
            voice_id="",
            project={"workspace_id": ws, "project_id": "", "sequence_id": sequence_id,
                     "video_track_id": video_track, "audio_track_id": audio_track},
        )
        assert not cancelled
        assert context["narration_subtitles"]["count"] == 0
        with SessionLocal() as db:
            assert db.query(Clip).filter(Clip.track_id == video_track).count() == 1


class Test数据边不决定该不该跑:
    def test_条件为假时_另有数据边的节点也跳过(self, fake_node) -> None:
        """挂在条件"真"出口上的节点,另从别处用数据边取值 —— 条件为假时它不该跑。

        此前数据边也算"激活":整片生成里没有口播的那一镜,「把口播对齐到这一镜」拿着空素材照跑,
        整条流程失败。
        """
        from app.domain.workflows.engine import execute_graph

        ws = _workspace()
        ran: list[str] = []
        fake_node("code", lambda db, workflow, config: ran.append(config.get("name", "")) or {"value": 7})
        graph = {
            "nodes": [
                {"id": "source", "type": "code", "config": {"name": "source"}},
                {"id": "gate", "type": "condition", "config": {"left": "", "op": "not_empty"}},
                {"id": "guarded", "type": "code", "config": {"name": "guarded", "value": ""}},
            ],
            "edges": [
                {"id": "c1", "source": "source", "target": "gate"},
                {"id": "c2", "source": "gate", "target": "guarded", "source_handle": "true"},
                {"id": "d1", "source": "source", "target": "guarded", "kind": "data",
                 "source_output": "value", "target_input": "value"},
            ],
        }
        context, _ = execute_graph(graph, wf_id=_workflow(ws).id, entry_is_root=True)
        assert ran == ["source"], f"条件为假却跑了:{ran}"
        assert "guarded" not in context

    def test_只有数据边时仍由数据边带起(self, fake_node) -> None:
        """画布会把控制边折叠成数据边;那种节点照旧跟着上游跑。"""
        from app.domain.workflows.engine import execute_graph

        ws = _workspace()
        fake_node("code", lambda db, workflow, config: {"value": config.get("value", 1)})
        graph = {
            "nodes": [
                {"id": "source", "type": "code", "config": {}},
                {"id": "sink", "type": "code", "config": {"value": ""}},
            ],
            "edges": [
                {"id": "d1", "source": "source", "target": "sink", "kind": "data",
                 "source_output": "value", "target_input": "value"},
            ],
        }
        context, _ = execute_graph(graph, wf_id=_workflow(ws).id, entry_is_root=True)
        assert context["sink"] == {"value": 1}
