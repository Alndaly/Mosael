"""工作流开的浏览器会话随**这次运行**结束而关掉 —— 成功、失败、取消都一样。

「打开浏览器」的说明写的是「临时 = 跑完即清」,而此前能关掉会话的只有「关闭浏览器」节点:
中途哪一步失败、或者用户点了取消,流程根本走不到它。于是:

· 临时会话的视图一直挂在执行器里,每失败一次多一个;
· 池档案会话的**租约**一直占着 —— 别的流程、智能体再想用这个已登录身份,只会被告知「占用中」,
  直到后端重启;
· 取消时正在等的那一步(比如等某个元素出现)要一直等到它自己超时才放手,而**排着的那个动作
  照样会被执行器领走去执行** —— 用户取消之后,「点发布」照样点了下去。

会话的归属也从「这条工作流」改成「这次运行」:同一条工作流并发跑两次时,此前两次拿到的是
**同一个**池档案会话(同 owner 复用),一次的「关闭」会关掉另一次正在用的视图。
"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserAction, BrowserSession, Job, User
from app.domain import browser as bdom
from app.domain.jobs import cancel_job, create_job, reset_parent_job, set_parent_job, wait_for_idle_jobs
from app.domain.workflows import WorkflowDomainError, create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.executors import browser as bx
from tests.util import fresh_client


def _ws() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _graph(*steps: dict) -> dict:
    nodes = [{"id": "start", "type": "start", "config": {}}, *steps]
    edges = [
        {"id": f"e{i}", "source": nodes[i]["id"], "target": nodes[i + 1]["id"]}
        for i in range(len(nodes) - 1)
    ]
    return {"nodes": nodes, "edges": edges}


def _start(ws: str, graph: dict) -> str:
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="RPA", graph=graph)
        return start_workflow_job(db, workflow, created_by=None).id


def _settle(job_id: str) -> str:
    for _ in range(100):
        with SessionLocal() as db:
            status = db.get(Job, job_id).status
        if status in ("succeeded", "failed"):
            return status
        time.sleep(0.1)
    raise AssertionError("工作流没跑完")


def _sessions(ws: str) -> list[BrowserSession]:
    with SessionLocal() as db:
        return list(db.query(BrowserSession).filter(BrowserSession.workspace_id == ws))


OPEN = {"id": "open", "type": "browser_open", "config": {}}


def test_中途失败_这次运行开的会话被关掉(monkeypatch) -> None:
    def run_action(sid, action, args, **kwargs):
        raise bdom.BrowserDomainError("browserErr_actionFailed")

    monkeypatch.setattr(bdom, "run_action", run_action)
    ws = _ws()
    job_id = _start(ws, _graph(OPEN, {"id": "click", "type": "browser_click", "config": {
        "session": "{{open.session}}", "selector": ".go",
    }}))
    assert _settle(job_id) == "failed"
    assert wait_for_idle_jobs(5)
    (session,) = _sessions(ws)
    assert session.status == "closed", "失败的运行把会话留在了执行器里"


def test_没接关闭节点_跑完也关(monkeypatch) -> None:
    """说明里写的是「临时 = 跑完即清」—— 不能要求每条流程都记得在末尾接一个「关闭浏览器」。"""
    monkeypatch.setattr(bdom, "run_action", lambda *a, **k: {})
    ws = _ws()
    job_id = _start(ws, _graph(OPEN))
    assert _settle(job_id) == "succeeded"
    (session,) = _sessions(ws)
    assert session.status == "closed"


def test_取消时正在等的那一步当场放手_排着的动作不再执行() -> None:
    """不 mock run_action:没有执行器来领,动作就停在 queued —— 正是取消那一刻的样子。"""
    ws = _ws()
    job_id = _start(ws, _graph(OPEN, {"id": "wait", "type": "browser_wait", "config": {
        "session": "{{open.session}}", "selector": "#never", "timeout_ms": 60000,
    }}))
    for _ in range(100):
        with SessionLocal() as db:
            pending = db.query(BrowserAction).filter(BrowserAction.action == "wait").first()
            if pending is not None:
                action_id = pending.id
                break
        time.sleep(0.1)
    else:
        raise AssertionError("等待动作一直没入队")

    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id))
    # 等待节点给了 60 秒 + 15 秒的余量。取消之后要在几秒内收场,而不是等满它。
    assert wait_for_idle_jobs(5), "取消之后,等待那一步还挂在那里等它自己超时"
    with SessionLocal() as db:
        assert db.get(BrowserAction, action_id).status == "failed", "排着的动作还会被执行器领走"
        (session,) = db.query(BrowserSession).filter(BrowserSession.workspace_id == ws).all()
        assert session.status == "closed"


def test_同一条工作流并发两次_不共用一个池档案会话(monkeypatch) -> None:
    monkeypatch.setattr(bdom, "run_action", lambda *a, **k: {})
    ws = _ws()
    with SessionLocal() as db:
        owner = db.query(User).order_by(User.created_at).first()
        profile_id = bdom.create_profile(db, workspace_id=ws, name="池号", owner=owner).id
        workflow = create_workflow(db, workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        runs = []
        for _ in range(2):
            # 替档案主人跑:池档案只有主人和被共享到的人能借(见 browser.usable_profile)。
            job = create_job(db, workspace_id=ws, kind="workflow", payload={}, created_by=owner.id)
            job.status = "running"
            runs.append(job.id)
        db.commit()

    config = {"session_mode": "pool", "profile_id": profile_id}
    token = set_parent_job(runs[0])
    try:
        with SessionLocal() as db:
            first = bx.browser_open(db, db.get(type(workflow), workflow.id), config)["session"]
    finally:
        reset_parent_job(token)
    token = set_parent_job(runs[1])
    try:
        with SessionLocal() as db, pytest.raises(WorkflowDomainError):
            bx.browser_open(db, db.get(type(workflow), workflow.id), config)
    finally:
        reset_parent_job(token)
    with SessionLocal() as db:
        assert db.get(BrowserSession, first).status == "open"
