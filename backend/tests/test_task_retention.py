"""任务行只由部署的保留清理删(ADR 0050 D29):结束超过 N 天(部署管理员定,默认 365,可选 90 / 180 / 永久)的整棵树删掉,
被定时任务运行、生成记录、发布记录指着的和记过用量的不删;运行产出全文和事件跟着任务走。

删法和事件清理同一个:挑出来的只是 id(读,不占写锁),删按批、一批一个事务,不把任务读成 ORM 对象 —— 此前「清空已结束」
逐个 ORM DELETE,1.2 万个任务点一次 41 秒,全程攥着写锁。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import event

from app.core.db import SessionLocal
from app.db.models import (
    GenerationJob,
    Job,
    ProviderUsageEvent,
    PublishAccount,
    PublishTask,
    ScheduledTask,
    ScheduledTaskRun,
    TaskEvent,
    WorkflowRunOutput,
    now,
)
from app.domain import deployment
from app.workers import scheduler
from tests.util import fresh_client, second_client


def _workspace(client=None) -> str:
    return (client or fresh_client()).post("/api/workspaces", json={"name": "W"}).json()["id"]


def _job(db, ws: str, *, days: int, status: str = "succeeded", kind: str = "render", parent: str | None = None) -> str:
    at = now() - timedelta(days=days)
    job = Job(workspace_id=ws, kind=kind, status=status, message="x", parent_job_id=parent, created_at=at, updated_at=at)
    db.add(job)
    db.flush()
    db.add(TaskEvent(job_id=job.id, type="e", payload={}))
    return job.id


def _left(ws: str) -> set[str]:
    with SessionLocal() as db:
        return {job.id for job in db.query(Job).filter(Job.workspace_id == ws)}


def test_结束超过保留天数的整棵删_别处指着的和记过用量的留下_运行产出跟着任务走() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        old = _job(db, ws, days=400)
        old_child = _job(db, ws, days=400, parent=old)
        old_run = _job(db, ws, days=400, kind="workflow")
        db.add(WorkflowRunOutput(job_id=old_run, node_id="ask", output_key="text", value="很早以前的回复"))
        recent = _job(db, ws, days=30)
        #: 顶层早就结束了,底下有一个结束得不久(或者还在跑):整棵留着
        mixed = _job(db, ws, days=400)
        mixed_child = _job(db, ws, days=10, parent=mixed)
        still = _job(db, ws, days=400)
        still_child = _job(db, ws, days=400, status="running", parent=still)
        #: 父任务早就没了的孤儿(老版本的「清空已结束」留下的)当顶层算
        orphan = _job(db, ws, days=400, parent="gone")
        # —— 别处的记录指着的 ——
        billed = _job(db, ws, days=400, kind="ai_generation")
        db.add(ProviderUsageEvent(workspace_id=ws, capability="image", operation="generate", idempotency_key="billed",
                                  job_id=billed))
        billed_parent = _job(db, ws, days=400)
        billed_child = _job(db, ws, days=400, parent=billed_parent)
        db.add(ProviderUsageEvent(workspace_id=ws, capability="video", operation="generate", idempotency_key="billed-child",
                                  job_id=billed_child))
        generated = _job(db, ws, days=400, kind="ai_generation")
        db.add(GenerationJob(workspace_id=ws, provider="p", model="m", kind="image", request={"prompt": "x"}, job_id=generated))
        task = ScheduledTask(workspace_id=ws, name="每天", kind="workflow", trigger_type="interval", schedule={"seconds": 60},
                             payload={})
        db.add(task)
        db.flush()
        scheduled = _job(db, ws, days=400, kind="workflow")
        db.add(ScheduledTaskRun(scheduled_task_id=task.id, job_id=scheduled, status="succeeded"))
        published = _job(db, ws, days=400, kind="publish")
        account = PublishAccount(workspace_id=ws, platform="bilibili", name="主号")
        db.add(account)
        db.flush()
        db.add(PublishTask(workspace_id=ws, account_id=account.id, job_id=published))
        db.commit()

    removed = scheduler.prune_jobs()

    assert removed == 4
    assert _left(ws) == {recent, mixed, mixed_child, still, still_child, billed, billed_parent, billed_child, generated,
                         scheduled, published}
    with SessionLocal() as db:
        assert db.query(TaskEvent).filter(TaskEvent.job_id.in_([old, old_child, old_run, orphan])).count() == 0
        assert db.query(WorkflowRunOutput).filter(WorkflowRunOutput.job_id == old_run).count() == 0, "运行产出跟着任务走"
    assert scheduler.prune_jobs() == 0, "幂等:剩下的都是该留的"


def test_保留天数由部署定_永久就什么都不删_改短了下一轮就按新的算() -> None:
    ws = _workspace()
    with SessionLocal() as db:
        half_year = _job(db, ws, days=200)
        db.commit()
    assert scheduler.prune_jobs() == 0, "默认 365 天:半年前的留着"

    with SessionLocal() as db:
        deployment.set_job_retention_days(db, None)
        db.commit()
    assert scheduler.prune_jobs() == 0
    assert _left(ws) == {half_year}

    with SessionLocal() as db:
        deployment.set_job_retention_days(db, 180)
        db.commit()
    assert scheduler.prune_jobs() == 1
    assert _left(ws) == set()


def test_部署管理员改保留天数_只认那几档_成员改不了() -> None:
    admin = fresh_client("admin")
    member = second_client("member")
    assert admin.get("/api/admin/job-retention").json() == {"days": 365}
    assert admin.put("/api/admin/job-retention", json={"days": 90}).json()["days"] == 90
    assert admin.put("/api/admin/job-retention", json={"days": None}).json()["days"] is None
    refused = admin.put("/api/admin/job-retention", json={"days": 3})
    assert refused.status_code == 422
    assert "90" in refused.json()["detail"]
    assert admin.get("/api/admin/job-retention").json()["days"] is None, "被拒的那次没有改动"
    assert member.get("/api/admin/job-retention").status_code == 403
    assert member.put("/api/admin/job-retention", json={"days": 90}).status_code == 403


def test_保留清理不把任务读成ORM对象_一批一个事务(monkeypatch) -> None:
    ws = _workspace()
    with SessionLocal() as db:
        for _ in range(5):
            _job(db, ws, days=400)
        parent = _job(db, ws, days=400)
        _job(db, ws, days=400, parent=parent)
        running = _job(db, ws, days=0, status="running")
        db.commit()
    monkeypatch.setattr(scheduler, "DELETE_JOBS_BATCH", 2)
    loaded = 0
    commits = 0

    def count_load(*_args) -> None:
        nonlocal loaded
        loaded += 1

    real = scheduler.unit_of_work

    def counted():
        nonlocal commits
        commits += 1
        return real()

    monkeypatch.setattr(scheduler, "unit_of_work", counted)
    event.listen(Job, "load", count_load)
    try:
        removed = scheduler.prune_jobs()
    finally:
        event.remove(Job, "load", count_load)

    assert removed == 7
    assert _left(ws) == {running}
    assert loaded == 0, f"保留清理把 {loaded} 个任务读成了 ORM 对象"
    assert commits == 4, f"7 个任务、一批 2 个,应该是 4 个事务,实际 {commits} 个"
