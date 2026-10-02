"""工作流往时间线上写:并行的写入排队、不再因版本号互相撞掉;时间线说「不行」时用工作流的话说。

## 现场

- 并行分支 / 并发的循环项同时「接到时间线」:各自在自己的会话里读到同一版,节点跑完才提交,
  后提交的那个按版本号 CAS 改 0 行 —— 整条工作流失败在「版本冲突」上。
- 指定了轨道就不查轨道类型:音频能接进视频轨。出点不夹到素材时长,超出去的是一段空白。
- 时间线域的拒绝原样漏出来:用户看到的是 `src_in must be non-negative`。
- 「清空时间线」逐条删:清掉 N 段就是 N 条撤销记录。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, SequenceOperation, Track, Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _setup() -> tuple[str, str, str]:
    """工作区 + 一条带视频轨的序列 + 一个工作流。返回 (workspace, sequence, workflow)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="编排", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return ws, sequence["id"], workflow.id


def _asset(ws: str, kind: str = "video", duration: float | None = 5.0) -> str:
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind=kind, name=f"a.{kind}", source="imported", file_key="x",
                      media_info={"duration": duration} if duration else {})
        db.add(asset)
        db.commit()
        return asset.id


def _run(node: str, wf_id: str, config: dict) -> dict:
    with SessionLocal() as db:
        out = get_executor(node)(db, db.get(Workflow, wf_id), config)
        db.commit()  # 引擎跑完一个节点提交(engine.run_node);这里就是那个引擎
        return out


def test_并发的循环项同时接到同一条时间线_一段都不丢_首尾相接() -> None:
    ws, sequence_id, wf_id = _setup()
    asset = _asset(ws, duration=5.0)
    body = {"nodes": [{"id": "put", "type": "timeline_append",
                       "config": {"sequence_id": "{{input.seq}}", "asset_id": "{{input.asset}}"}}], "edges": []}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "each", "type": "loop_foreach", "config": {
                "items": list(range(8)), "concurrency": 4, "body": body, "output": "{{put.clip_id}}",
                "inputs": {"seq": sequence_id, "asset": asset}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "each"}],
    }
    context, cancelled = execute_graph(graph, wf_id=wf_id)
    assert not cancelled
    assert len(set(context["each"]["results"])) == 8
    with SessionLocal() as db:
        starts = sorted(clip.timeline_start for clip in db.query(Clip).filter(Clip.sequence_id == sequence_id))
    assert starts == [index * 5.0 for index in range(8)], "并行接上去的几段叠在了一起,或者丢了"


def test_指定的轨道类型不对_拦下() -> None:
    ws, sequence_id, wf_id = _setup()
    with SessionLocal() as db:
        video_track = db.query(Track).filter(Track.sequence_id == sequence_id, Track.kind == "video").first().id
    with pytest.raises(WorkflowDomainError) as caught:
        _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": _asset(ws, "audio"),
                                        "track_id": video_track})
    assert caught.value.key == "seqErr_trackKindMismatch"


def test_出点夹到素材时长_图片不夹() -> None:
    ws, sequence_id, wf_id = _setup()
    out = _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": _asset(ws, duration=5.0), "end": 9})
    assert out["timeline_end"] - out["timeline_start"] == 5.0
    still = _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": _asset(ws, "image", None), "end": 8})
    assert still["timeline_end"] - still["timeline_start"] == 8.0, "图片定格多久由节点说了算"


def test_截取起点为负_用工作流的话说() -> None:
    ws, sequence_id, wf_id = _setup()
    with pytest.raises(WorkflowDomainError) as caught:
        _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": _asset(ws), "start": -1})
    assert caught.value.key == "wfErr_trimStartNegative"


def test_时间线域的拒绝转成工作流错误_带着_key() -> None:
    """文档没有画面和声音可放 —— 时间线域说不行,节点把那句话带着 key 转出来,而不是原样漏出去。"""
    ws, sequence_id, wf_id = _setup()
    with pytest.raises(WorkflowDomainError) as caught:
        _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": _asset(ws, "document", None), "end": 3})
    assert caught.value.key == "seqErr_assetNotMedia"


def test_清空时间线只记一条操作_撤销一步全部找回() -> None:
    ws, sequence_id, wf_id = _setup()
    asset = _asset(ws)
    for _ in range(3):
        _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": asset})
    with SessionLocal() as db:
        before = db.query(SequenceOperation).filter(SequenceOperation.sequence_id == sequence_id).count()
    assert _run("timeline_clear", wf_id, {"sequence_id": sequence_id})["removed"] == 3
    with SessionLocal() as db:
        added = db.query(SequenceOperation).filter(SequenceOperation.sequence_id == sequence_id).count() - before
        assert db.query(Clip).filter(Clip.sequence_id == sequence_id).count() == 0
    assert added == 1, f"清空 3 段记了 {added} 条撤销记录"
    assert _run("timeline_clear", wf_id, {"sequence_id": sequence_id})["removed"] == 0, "空时间线清空不该报错"


def test_字幕段落缺时间码_报错而不是当成第_0_秒() -> None:
    """起点字段写错一个字,此前每一条字幕都从片头开始、叠成一摞,节点照样成功。"""
    ws, sequence_id, wf_id = _setup()
    with pytest.raises(WorkflowDomainError) as caught:
        _run("generate_subtitles", wf_id, {"sequence_id": sequence_id,
                                           "segments": [{"start": 0, "end": 1, "text": "一"}, {"end": 2, "text": "二"}]})
    assert caught.value.key == "wfErr_segmentTimecode"
    assert caught.value.params["index"] == "2"
    out = _run("generate_subtitles", wf_id, {"sequence_id": sequence_id, "segments": [{"start": 0, "end": 1, "text": "一"}]})
    assert out["count"] == 1, "第 0 秒开始的段落是合法的"


def test_工作流对时间线的改动记在跑它的人头上() -> None:
    """此前工作流节点不传 actor:操作日志里是「没有人」,「只撤我自己的」撤不到它,冲突时也说不出是谁改的。"""
    from sqlalchemy import select

    from app.db.models import Job
    from app.domain.jobs import reset_parent_job, set_parent_job
    from tests.util import user_id

    ws, sequence_id, wf_id = _setup()
    me = user_id("tester")
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind="workflow", status="running", created_by=me)
        db.add(job)
        db.commit()
        job_id = job.id
    token = set_parent_job(job_id)
    try:
        _run("timeline_append", wf_id, {"sequence_id": sequence_id, "asset_id": _asset(ws)})
        _run("edit_timeline", wf_id, {"sequence_id": sequence_id,
                                      "operations": [{"kind": "add_track", "track_kind": "audio"}]})
    finally:
        reset_parent_job(token)
    with SessionLocal() as db:
        actors = db.scalars(select(SequenceOperation.actor_id).where(SequenceOperation.sequence_id == sequence_id)).all()
    assert actors and set(actors) == {me}
