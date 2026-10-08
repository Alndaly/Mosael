"""任务事件的保留清理:**集合式、分批提交**,不把任务读成 ORM 对象(任务行的保留清理同一个做法,见 test_task_retention)。

此前它和当时的「清空已结束」都是先把任务整行读进会话、再逐个 ORM DELETE —— 而 ORM 的 DELETE 每一次都把身份映射里的全部对象过一遍,
任务越多越是平方级:在维护者库副本上放大到 1.2 万个任务,清理 11.6 秒、「清空已结束」41.5 秒;3.2 万个,清理 67 秒。
而且全程一个事务攥着写锁,另一个连接的写入 5 秒后报 database is locked。清理还在启动后第 5 秒就跑一次。

现在:挑出来的只是 id(读,不占写锁),删按批、一批一个事务。这里钉住三件事:规则没变;一个任务对象都不加载;
真的是一批一个事务。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import event

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent, now
from app.domain import jobs as jobs_bus
from app.workers import scheduler
from tests.util import fresh_client


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _job(ws: str, *, status: str, events: int, kind: str = "render", age_days: int = 0, parent: str | None = None) -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind=kind, status=status, message="x", parent_job_id=parent)
        db.add(job)
        db.flush()
        for index in range(events):
            db.add(TaskEvent(job_id=job.id, type=f"e{index}", payload={}))
        if age_days:
            job.updated_at = now() - timedelta(days=age_days)
        db.commit()
        return job.id


def _events(job_id: str) -> int:
    with SessionLocal() as db:
        return db.query(TaskEvent).filter(TaskEvent.job_id == job_id).count()


class _Watch:
    """数一数:加载了几个 Job 对象、提交了几次。"""

    def __init__(self, monkeypatch) -> None:
        self.loaded = 0
        self.commits = 0
        event.listen(Job, "load", self._loaded)
        real = scheduler.unit_of_work

        def counted():
            self.commits += 1
            return real()

        monkeypatch.setattr(scheduler, "unit_of_work", counted)

    def _loaded(self, *_args) -> None:
        self.loaded += 1

    def close(self) -> None:
        event.remove(Job, "load", self._loaded)


def test_event_retention_keeps_the_rules_and_deletes_in_batches(monkeypatch) -> None:
    ws = _workspace()
    active = _job(ws, status="running", events=10)
    recent = [_job(ws, status="succeeded", events=10) for _ in range(3)]
    old = _job(ws, status="failed", events=10, age_days=40)
    workflow = _job(ws, status="failed", events=12, kind="workflow")
    monkeypatch.setattr(scheduler, "PRUNE_BATCH", 4)
    watch = _Watch(monkeypatch)
    try:
        removed = scheduler.prune_events()
    finally:
        watch.close()

    assert removed == 3 * 5 + 10
    assert _events(active) == 10, "进行中的任务全留"
    assert [_events(one) for one in recent] == [5, 5, 5], "已结束的留最近 5 条"
    assert _events(old) == 0, "结束超过 30 天的事件全删"
    assert _events(workflow) == 12, "工作流在窗口内全留(执行历史靠事件配对还原每个节点)"
    assert watch.loaded == 0, f"清理把 {watch.loaded} 个任务读成了 ORM 对象 —— 平方级就是从这儿来的"
    assert watch.commits == 7, f"25 条、一批 4 条,应该是 7 个事务,实际 {watch.commits} 个"


def test_prune_runs_with_the_shared_selection(monkeypatch) -> None:
    """一次删完的入口(测试、小库)和分批的入口认的是同一份「该删哪些」。"""
    ws = _workspace()
    recent = _job(ws, status="succeeded", events=8)
    with SessionLocal() as db:
        assert len(jobs_bus.prunable_task_events(db)) == 3
        assert jobs_bus.prune_task_events(db) == 3
        db.commit()
    assert _events(recent) == 5
