"""重启收尾是**一次用例、一个事务**:全部收完才提交,提交钩子(收拾、送回执、接着干)在那之后才跑。

此前任务那一步自己提交,钩子当场就跑:孤儿任务的回执在空闲的对话里起了一轮,紧接着「把卡住的会话拨回 idle」把这一轮
当成重启前的孤儿拨回去,还补了一句「上一轮对话因后端重启而中断,请重新发送」—— 而那一轮正在跑,用户再发一句就是同一个
会话两轮并发。反过来,重启前正卡着的会话:回执落成「待送」,随后被拨回 idle,回执就一直躺着。

这里跑的是启动时真正调的那一个函数(domain/restart.settle_previous_run),不是照抄几行。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession, Job, User
from app.domain import jobs as jobs_bus
from app.domain import restart
from app.domain.agent import host
from app.domain.agent.receipts import receipt_to_session
from tests.util import fresh_client


def _setup(session_status: str) -> tuple[str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws, "title": "T"}).json()["id"]
    with SessionLocal() as db:
        user = db.scalars(select(User)).first()
        db.get(AgentSession, sid).status = session_status
        # 智能体交出去的一个导出,后端退出时还在跑
        job = Job(workspace_id=ws, kind="render", payload={"subject": "成片", "receipt": receipt_to_session(sid)},
                  created_by=user.id, status="running")
        db.add(job)
        db.commit()
        return sid, job.id


def _messages(sid: str) -> list[str]:
    with SessionLocal() as db:
        return [m.content for m in db.scalars(select(AgentMessage).where(AgentMessage.session_id == sid))]


@pytest.fixture()
def turns(monkeypatch) -> list[str]:
    """不真的起一轮(要 sidecar):记下「起了」;会话照常被回执那一轮抢成 running。"""
    started: list[str] = []
    monkeypatch.setattr(host, "_start_turn", lambda session_id, prompt, token, actor_id=None: started.append(session_id))
    return started


def test_a_receipt_at_startup_is_not_reported_as_an_interrupted_turn(turns) -> None:
    sid, job_id = _setup("idle")

    restart.settle_previous_run()

    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.get(AgentSession, sid).status == "running", "回执起的那一轮被当成孤儿拨回了 idle"
    assert turns == [sid], "回执应该在对话里起一轮(也只起一轮)"
    assert host.INTERRUPTED_NOTICE not in _messages(sid), "上一轮根本没被打断,却补了一句「已中断」"


def test_a_turn_cut_off_by_the_restart_is_closed_and_still_gets_the_receipt(turns) -> None:
    sid, _job_id = _setup("running")

    restart.settle_previous_run()

    assert host.INTERRUPTED_NOTICE in _messages(sid), "被重启打断的那一轮要说一声"
    assert turns == [sid], "回执没送出去(落成了「待送」,而之后再也没有一轮来捞它)"


def test_nothing_is_committed_and_nobody_is_woken_if_settling_fails(turns, monkeypatch) -> None:
    sid, job_id = _setup("idle")

    def broken(_db) -> int:
        raise RuntimeError("disk gone")

    monkeypatch.setattr("app.domain.assets.reconcile_broken_media_info", broken)
    with pytest.raises(RuntimeError):
        restart.settle_previous_run()

    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "running", "收尾中途失败,前面那几步不该已经提交"
    assert turns == []


def test_remote_work_is_resumed_only_after_everything_is_settled(monkeypatch) -> None:
    """接着干的(远端还在生成的那种)在收尾提交之后才开始:它看到的库里,别的孤儿已经落了终态。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        resumable = Job(workspace_id=ws, kind="fake_remote", status="running", payload={})
        orphan = Job(workspace_id=ws, kind="render", status="running", payload={})
        db.add_all([resumable, orphan])
        db.commit()
        resumable_id, orphan_id = resumable.id, orphan.id
    seen: dict[str, str] = {}

    def resume(job_id: str) -> bool:
        with SessionLocal() as fresh:
            seen[job_id] = fresh.get(Job, orphan_id).status
        return True

    monkeypatch.setitem(jobs_bus._RESUMERS, "fake_remote", jobs_bus._Resumer(can_resume=lambda db, job: True, resume=resume))

    restart.settle_previous_run()

    assert seen == {resumable_id: "failed"}, "接着干的在收尾提交之前就开始了(它看到的孤儿还是 running)"


def test_settling_jobs_and_browser_sessions_together_does_not_lock_itself_out() -> None:
    """浏览器那一项此前自己开事务:任务那一步已经在外层事务里写过、攥着写锁,它的写入排在后面等满 busy_timeout,
    启动失败。后端被杀时正跑着一个用浏览器节点的工作流,就是这两样同时都有。"""
    import time

    from app.db.models import BrowserAction, BrowserSession
    from app.domain import browser

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    from datetime import timedelta

    from app.db.models import now

    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind="workflow", status="running", payload={})
        # 外部执行器的一条租约在后端停着的时候过期了:收尾时按条件更新把它判失败 —— 那一下就在外层事务里拿了写锁。
        leased = Job(workspace_id=ws, kind="publish", status="running", payload={}, lease_token="t", lease_worker="w",
                     lease_expires_at=now() - timedelta(minutes=5))
        db.add_all([job, leased])
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="navigate", args={}, status="running"))
        db.commit()
        job_id = job.id

    started = time.monotonic()
    settled = restart.settle_previous_run()
    took = time.monotonic() - started

    assert took < 4, f"收尾等了 {took:.1f} 秒 —— 自己的两个事务在抢写锁"
    assert settled["jobs"] == 2 and settled["browser_actions"] == 1  # 中断的工作流 + 过期的租约
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.get(BrowserSession, sid).status == "closed"
