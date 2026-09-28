"""任务中心的「清空已结束」清的是**面板上列着的那些** —— 已结束的顶层任务,连同它们收纳的子任务。

此前是「这个工作区里所有已结束的行」:一个还在跑的工作流底下做完的几步被一起删掉(面板上根本没列它们,
父任务的详情里却凭空少了几步;配音这类父任务还要回头读子任务的失败原因)。反过来,顶层任务结束了、它派生的
子任务还在跑的,删掉父任务会让那个子任务成为面板上永远看不见的孤儿。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent
from tests.util import fresh_client


def _job(db, workspace_id: str, status: str, parent: str | None = None) -> str:
    job = Job(workspace_id=workspace_id, kind="render", status=status, message="x", parent_job_id=parent)
    db.add(job)
    db.flush()
    db.add(TaskEvent(job_id=job.id, type="e", payload={}))
    return job.id


def test_只清整棵都结束了的顶层任务_连同子任务() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        done = _job(db, ws, "succeeded")
        done_child = _job(db, ws, "failed", parent=done)
        done_grandchild = _job(db, ws, "succeeded", parent=done_child)
        running = _job(db, ws, "running")
        running_finished_child = _job(db, ws, "succeeded", parent=running)
        finished_with_live_child = _job(db, ws, "succeeded")
        live_child = _job(db, ws, "running", parent=finished_with_live_child)
        # 旧版本的清空留下的孤儿:父任务早没了。面板看不见它,它也不再属于任何还在的东西。
        orphan = _job(db, ws, "failed", parent="gone")
        db.commit()

    removed = client.delete(f"/api/jobs/finished?workspace_id={ws}").json()
    assert removed == {"removed": 4}

    with SessionLocal() as db:
        left = {job.id for job in db.query(Job).filter(Job.workspace_id == ws)}
        assert left == {running, running_finished_child, finished_with_live_child, live_child}
        assert not {done, done_child, done_grandchild, orphan} & left
        # 删掉的任务的事件一起走,留下的不动。
        assert {event.job_id for event in db.query(TaskEvent)} >= left
        assert not {event.job_id for event in db.query(TaskEvent)} & {done, done_child, done_grandchild, orphan}
