"""智能体自己盯着任务跑完了,回执就不再送回这次对话。

用户截图:智能体提交 MinerU 重新解析之后自己 get_job 轮询到「完成」、读了结果、分析完;回执照样在这一轮跑着的时候
到了,进了排队,这一轮一结束又被当成一条新消息跑一轮,智能体回「收到,这正是刚才那次解析的回执,不需要再做别的
处理」。用户:「这种回执本身智能体调用 job 获取结果中就有了的吧,为何还会独立显示」。
"""

from __future__ import annotations

import mcp_server
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession, Job, User
from app.domain import jobs as jobs_domain
from app.domain.agent import host, receipts
from tests.util import fresh_client


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first().id
        for session_id in ("s-mine", "s-other"):
            db.add(AgentSession(id=session_id, workspace_id=ws, owner_user_id=me, title=session_id))
        db.commit()
    return ws, me


def _job(ws: str, me: str, session_id: str) -> str:
    with SessionLocal() as db:
        job = jobs_domain.create_job(db, workspace_id=ws, kind="document_parse", created_by=me,
                                     payload={"subject": "签章文件.pdf", "receipt": receipts.receipt_to_session(session_id)})
        db.commit()
        return job.id


def _queued_receipt(session_id: str, job_id: str) -> None:
    """回执在这一轮跑着的时候到:post_job_receipt 抢不到会话,落成一条「待送」的回执(不进队列)。"""
    with SessionLocal() as db:
        db.add(AgentMessage(session_id=session_id, role=host.JOB_RECEIPT_ROLE, content="「签章文件.pdf」已完成。",
                            payload={"job_id": job_id, "undelivered": True}))
        db.commit()


def _finish(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "succeeded"
        db.commit()


def _queued(session_id: str) -> list[str]:
    """还等着交给智能体的回执(按任务 id)。"""
    with SessionLocal() as db:
        rows = db.query(AgentMessage).filter_by(session_id=session_id, role=host.JOB_RECEIPT_ROLE).all()
        return [str((row.payload or {}).get("job_id")) for row in rows if (row.payload or {}).get("undelivered")]


def test_回执已经落库待送_智能体get_job看到终态就拿掉(monkeypatch) -> None:
    ws, me = _setup()
    monkeypatch.setattr(receipts.host, "post_job_receipt", lambda *args, **kwargs: None)
    job_id = _job(ws, me, "s-mine")
    _finish(job_id)
    _queued_receipt("s-mine", job_id)
    assert _queued("s-mine") == [job_id]

    with mcp_server.calling_as(user_id=me, session_id="s-mine"):
        seen = mcp_server.get_job(job_id)
    assert seen["status"] == "succeeded"
    assert _queued("s-mine") == [], "看到终态之后,待送的回执还会再跑一轮"
    with SessionLocal() as db:
        assert db.get(Job, job_id).payload["receipt"]["seen"] is True


def test_看到终态之后才轮到送_就不送(monkeypatch) -> None:
    ws, me = _setup()
    posted: list[str] = []
    monkeypatch.setattr(receipts.host, "post_job_receipt", lambda db, session, content, *a, **k: posted.append(content))
    job_id = _job(ws, me, "s-mine")
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "succeeded"
        job.payload = {**job.payload, "receipt": {**job.payload["receipt"], "seen": True}}
        receipts.deliver(db, job, job.payload["receipt"])
    assert posted == []


def test_没看到的照样送_还在跑时查一眼不算(monkeypatch) -> None:
    """回执的本意不变:智能体提交完就断了线索的,跑完照样告诉它。"""
    ws, me = _setup()
    posted: list[str] = []
    monkeypatch.setattr(receipts.host, "post_job_receipt", lambda db, session, content, *a, **k: posted.append(content))
    job_id = _job(ws, me, "s-mine")
    with mcp_server.calling_as(user_id=me, session_id="s-mine"):
        assert mcp_server.get_job(job_id)["status"] != "succeeded"
    _finish(job_id)
    assert posted == ["「签章文件.pdf」已完成。"]


def test_别的会话看一眼_不替这次对话确认(monkeypatch) -> None:
    ws, me = _setup()
    monkeypatch.setattr(receipts.host, "post_job_receipt", lambda *args, **kwargs: None)
    job_id = _job(ws, me, "s-mine")
    _finish(job_id)
    _queued_receipt("s-mine", job_id)
    with mcp_server.calling_as(user_id=me, session_id="s-other"):
        mcp_server.get_job(job_id)
    assert _queued("s-mine") == [job_id]
