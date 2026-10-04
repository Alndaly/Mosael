"""浏览器自动化的悬浮卡片要写明它属于哪个工作流的哪次运行 —— 卡片只知道会话 id,这里回答「这个会话是谁的」。

实测(真实执行器):几条工作流同时跑时,右下角叠着几张没有标题的卡片,分不出哪张是哪次运行的。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Job, Workflow
from app.domain import browser
from tests.util import fresh_client, second_client, user_id


def _workflow_run(ws: str, name: str) -> tuple[str, str]:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name=name, graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        job = Job(workspace_id=ws, kind="workflow", status="running", payload={"workflow_id": workflow.id},
                  created_by=user_id())
        db.add(job)
        db.commit()
        return workflow.id, job.id


def _session(ws: str, *, owner_kind: str, owner_id: str | None) -> str:
    with SessionLocal() as db:
        return browser.open_session(db, workspace_id=ws, owner_kind=owner_kind, owner_id=owner_id, actor=None).id


def test_工作流运行开的会话_说出工作流名和那次运行() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow_id, job_id = _workflow_run(ws, "爆款拆解")
    sid = _session(ws, owner_kind="workflow", owner_id=job_id)

    body = client.get(f"/api/browser/sessions/{sid}").json()
    assert body["id"] == sid
    run = body["run"]
    assert (run["workflow_id"], run["workflow_name"], run["job_id"]) == (workflow_id, "爆款拆解", job_id)
    assert run["started_at"]


def test_智能体开的会话_没有运行可说() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = _session(ws, owner_kind="agent", owner_id="conversation-1")
    body = client.get(f"/api/browser/sessions/{sid}").json()
    assert body == {"id": sid, "run": None}


def test_不是会话的编号_和别的工作区的会话_一律找不到() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _, job_id = _workflow_run(ws, "W1")
    sid = _session(ws, owner_kind="workflow", owner_id=job_id)
    # 发布账号的卡片 id 是账号 id,不是会话:卡片照样来问,回 404 就不改标题
    assert client.get("/api/browser/sessions/persist:pool-abc").status_code == 404
    outsider = second_client()
    assert outsider.get(f"/api/browser/sessions/{sid}").status_code == 404
