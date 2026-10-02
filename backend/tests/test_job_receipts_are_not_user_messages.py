"""后台任务的回执不是用户消息:不进排队、不各起一轮。

用户截图:智能体连着提交一串配音,每条跑完都用 `post_user_message(..., origin_job_id=…)` 以用户的名义送回
对话 —— 会话正忙就带 `queued` 进了排队,输入框上方排了七八条「「配音 3」已完成,素材 id:…」,还带着
Steer 和删除;这一轮结束后又每条各跑一轮。会话空闲时也会在队列里闪一下才被取走。用户:「明明是任务的返回,
但有一瞬间会显示在消息队列中」「全都在消息队列中了」。

钉住的几条(都走真实入口:任务落终态 → jobs 的 after_commit → receipts.deliver):
  · 回执在数据上就不是用户消息(自己的角色),**从头到尾**不出现在队列接口里;
  · 智能体忙时到的 N 条:这一轮结束后**只起一轮**,那一轮看得到全部 N 条;
  · 空闲时到的:直接起一轮;
  · 智能体自己 get_job 看到了终态的(acknowledge_seen):不再送,也不再为它起一轮;
  · 有人排了一条话、回执也到了:回执搭那一轮的车,不单独再起一轮。
"""

from __future__ import annotations

import threading
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event

import mcp_server
from app.ai.sidecar.pi_client import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession, Job, User
from app.domain import jobs as jobs_domain
from app.domain.agent import host, receipts
from tests.test_agent_queue import _session, _wait_until
from tests.util import fresh_client


class Turns:
    """假模型:记下每一轮收到的提示词;第一轮停在闸门上,好在「智能体正忙」的时候送回执。"""

    def __init__(self, hold_first: bool) -> None:
        self.prompts: list[str] = []
        self.gate = threading.Event()
        if not hold_first:
            self.gate.set()

    def __call__(self, *args: Any, **kwargs: Any) -> TurnResult:
        self.prompts.append(str(kwargs.get("prompt") or (args[1] if len(args) > 1 else "")))
        if len(self.prompts) == 1:
            assert self.gate.wait(15), "测试没放行第一轮"
        return TurnResult(text="好的")


@pytest.fixture
def model(monkeypatch):
    """装上假模型。**收尾时一定放行并等它跑完** —— 断言半路失败时,停在闸门上的那一轮会活进下一条测试,
    调到下一条测试装的假模型上(红的那条是无辜的)。"""
    made: list[Turns] = []

    def make(*, hold_first: bool) -> Turns:
        turns = Turns(hold_first=hold_first)
        made.append(turns)
        monkeypatch.setattr(host, "run_turn", turns)
        return turns

    yield make
    for turns in made:
        turns.gate.set()
    host.wait_for_idle_turns(20)


@pytest.fixture
def written(monkeypatch) -> list[dict[str, Any]]:
    """这个会话里**曾经写进库**的每一条消息(插入和更新都算)—— 「从头到尾」靠它判,不靠事后看一眼。"""
    seen: list[dict[str, Any]] = []

    def record(_mapper, _connection, target: AgentMessage) -> None:
        seen.append({"role": target.role, "content": target.content, "payload": dict(target.payload or {})})

    event.listen(AgentMessage, "after_insert", record)
    event.listen(AgentMessage, "after_update", record)
    yield seen
    event.remove(AgentMessage, "after_insert", record)
    event.remove(AgentMessage, "after_update", record)


def _me() -> str:
    with SessionLocal() as db:
        return db.query(User).order_by(User.created_at).first().id


def _workspace(sid: str) -> str:
    with SessionLocal() as db:
        return db.get(AgentSession, sid).workspace_id


def _dub(sid: str, n: int) -> str:
    """一条配音任务,回执寄回这次对话。"""
    with SessionLocal() as db:
        job = jobs_domain.create_job(
            db, workspace_id=_workspace(sid), kind="tts", created_by=_me(),
            payload={"subject": f"配音 {n}", "receipt": receipts.receipt_to_session(sid)},
        )
        db.commit()
        return job.id


def _finish(job_id: str, asset_id: str) -> None:
    """任务走到终态 —— 提交之后,jobs 的 after_commit 调 receipts.deliver(真实入口)。"""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "succeeded"
        job.result = {"asset_id": asset_id}
        db.commit()


def _queue(client, sid: str) -> list[dict]:
    return client.get(f"/api/agent/sessions/{sid}/queue").json()


def _messages(client, sid: str) -> list[dict]:
    return client.get(f"/api/agent/sessions/{sid}/messages").json()


def _busy(client, sid: str) -> None:
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "把五段旁白都配上音"})
    _wait_until(lambda: _status(sid) == "running")


def _status(sid: str) -> str:
    with SessionLocal() as db:
        return db.get(AgentSession, sid).status


def _settle(turns: Turns) -> None:
    turns.gate.set()
    assert host.wait_for_idle_turns(20), "还有轮次没跑完"


def test_智能体忙时连到五条回执_不进队列_这一轮结束后只起一轮_那一轮看得到全部(model, written) -> None:
    turns = model(hold_first=True)
    client = fresh_client()
    sid = _session(client)
    _busy(client, sid)

    jobs = [_dub(sid, n) for n in range(1, 6)]
    for n, job_id in enumerate(jobs, start=1):
        _finish(job_id, f"asset-{n}")
        assert _queue(client, sid) == [], f"第 {n} 条回执进了排队"

    receipts_now = [one for one in _messages(client, sid) if one["role"] != "user" and one["role"] != "assistant"]
    assert len(receipts_now) == 5, "回执要在对话里看得见(画成任务通知),不是藏起来"
    assert all(one["role"] == "job_receipt" for one in receipts_now)
    assert [one["content"] for one in _messages(client, sid) if one["role"] == "user"] == ["把五段旁白都配上音"]

    _settle(turns)

    assert len(turns.prompts) == 2, f"五条回执应该合成一轮送,实际起了 {len(turns.prompts) - 1} 轮"
    for n in range(1, 6):
        assert f"「配音 {n}」已完成,素材 id:asset-{n}" in turns.prompts[1]
        assert jobs[n - 1] in turns.prompts[1], "模型要知道是哪个任务的回执"
    assert _queue(client, sid) == []
    assert not any(row["payload"].get("queued") for row in written if row["role"] != "user"), "回执曾经进过排队"
    assert not any(row["role"] == "user" and row["payload"].get("from_job") for row in written), "回执曾经以用户消息落库"


def test_空闲时到的回执_直接起一轮_队列从头到尾看不到它(model, written) -> None:
    turns = model(hold_first=False)
    client = fresh_client()
    sid = _session(client)

    job_id = _dub(sid, 1)
    _finish(job_id, "asset-1")
    assert _queue(client, sid) == []
    _settle(turns)

    assert len(turns.prompts) == 1
    assert "「配音 1」已完成,素材 id:asset-1" in turns.prompts[0] and job_id in turns.prompts[0]
    assert not any(row["payload"].get("queued") for row in written), "空闲时到的回执也在队列里闪过一下"
    shown = [one for one in _messages(client, sid) if one["role"] == "job_receipt"]
    assert [one["content"] for one in shown] == ["「配音 1」已完成,素材 id:asset-1。"]
    assert not shown[0]["payload"].get("undelivered"), "已经交给智能体的回执还标着没送"


def test_智能体自己get_job看到了终态_回执不再送_也不为它起一轮(model, written) -> None:
    turns = model(hold_first=True)
    client = fresh_client()
    sid = _session(client)
    _busy(client, sid)

    job_id = _dub(sid, 1)
    _finish(job_id, "asset-1")
    assert [one["role"] for one in _messages(client, sid)].count("job_receipt") == 1

    with mcp_server.calling_as(user_id=_me(), session_id=sid):
        assert mcp_server.get_job(job_id)["status"] == "succeeded"
    assert [one["role"] for one in _messages(client, sid)].count("job_receipt") == 0, "看到终态之后,回执还挂着等送"

    _settle(turns)
    assert len(turns.prompts) == 1, "智能体已经看到的回执又跑了一轮"


def test_看到终态在先_任务落终态时就不送(model) -> None:
    turns = model(hold_first=False)
    client = fresh_client()
    sid = _session(client)
    job_id = _dub(sid, 1)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.payload = {**job.payload, "receipt": {**job.payload["receipt"], "seen": True}}
        db.commit()

    _finish(job_id, "asset-1")
    _settle(turns)
    assert turns.prompts == []
    assert [one["role"] for one in _messages(client, sid)].count("job_receipt") == 0


def test_有人排了一条话_回执搭那一轮的车_不单独再起一轮(model, written) -> None:
    turns = model(hold_first=True)
    client = fresh_client()
    sid = _session(client)
    _busy(client, sid)

    _finish(_dub(sid, 1), "asset-1")
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "顺便把音量调大一点"})
    assert [one["content"] for one in _queue(client, sid)] == ["顺便把音量调大一点"], "用户自己排的那条照旧在队列里"
    _finish(_dub(sid, 2), "asset-2")

    _settle(turns)
    assert len(turns.prompts) == 2, f"回执和排队的话应当一轮处理完,实际 {len(turns.prompts)} 轮"
    second = turns.prompts[1]
    assert "「配音 1」已完成" in second and "「配音 2」已完成" in second and "顺便把音量调大一点" in second
    assert second.index("「配音 2」已完成") < second.index("顺便把音量调大一点"), "回执要在用户那句话之前交代"
    order = [(one["role"], one["content"]) for one in _messages(client, sid)]
    assert order.index(("user", "顺便把音量调大一点")) > order.index(("job_receipt", "「配音 2」已完成,素材 id:asset-2。"))


def test_存量回执迁成自己的角色_排着的那条迁成待送_重跑不动() -> None:
    from app.core.db import engine
    from app.db import migrations

    client = fresh_client()
    sid = _session(client)
    me = _me()
    with SessionLocal() as db:
        db.add_all([
            AgentMessage(id="sent", session_id=sid, role="user", content="「旧配音」已完成。", payload={"from_job": "j-old"}),
            AgentMessage(id="waiting", session_id=sid, role="user", content="「排着的」已完成。",
                         payload={"from_job": "j-wait", "queued": True, "queued_by": me}),
            AgentMessage(id="mine", session_id=sid, role="user", content="我自己说的", payload={"queued": True, "queued_by": me}),
            AgentMessage(id="agent", session_id=sid, role="user", content="别的会话来的", payload={"from_agent_session": "s2"}),
        ])
        db.commit()

    migrations._migrate_job_receipts_get_their_own_role()
    migrations._migrate_job_receipts_get_their_own_role()

    with engine.begin() as conn:
        rows = {
            row.id: (row.role, __import__("json").loads(row.payload))
            for row in conn.execute(sa.text("SELECT id, role, payload FROM agent_messages"))
        }
    assert rows["sent"] == ("job_receipt", {"job_id": "j-old"})
    assert rows["waiting"] == ("job_receipt", {"job_id": "j-wait", "undelivered": True, "deliver_as": me})
    assert rows["mine"] == ("user", {"queued": True, "queued_by": me})
    assert rows["agent"] == ("user", {"from_agent_session": "s2"})
    assert [one["content"] for one in _queue(client, sid)] == ["我自己说的"]
