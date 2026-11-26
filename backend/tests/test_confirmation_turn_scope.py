"""确认卡属于一轮对话:活着的回合必须绑 turn;空闲会话可无主开卡,但收尾后不能再挂旧轮。"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import AgentSession, ToolConfirmation, User
from app.domain.agent import stream
from app.domain.agent.card_expiry import EXPIRED, expire_session_cards
from app.domain.agent.errors import ConfirmationError
from app.domain.agent.proposals import propose
from tests.test_agent_queue import _session
from tests.util import fresh_client


def _user(db) -> User:
    return db.query(User).filter(User.username == "tester").one()


def test_开卡记录当前轮_空闲时无主开卡_收尾后拒绝开新卡() -> None:
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        user = _user(db)
        session = db.get(AgentSession, sid)
        session.status = "running"
        stream._stream_reset(sid)
        card = propose(
            db, user, workspace_id=session.workspace_id, tool="browser_open",
            payload={"url": "https://example.com"}, session_id=sid, tool_call_id="call-1",
            require_live_turn=True,
        )
        db.commit()
        assert card.turn_id == stream._stream_turn_id(sid)

    with SessionLocal() as db:
        session = db.get(AgentSession, sid)
        session.status = "idle"
        db.commit()
        #: 空闲会话没有轮次可绑(直连工具/外部通道):允许开成无主卡,由会话边界兜底作废。
        card = propose(
            db, _user(db), workspace_id=session.workspace_id, tool="browser_open",
            payload={"url": "https://example.com"}, session_id=sid, tool_call_id="call-2",
            require_live_turn=True,
        )
        assert card.turn_id is None
        db.commit()

    with SessionLocal() as db:
        session = db.get(AgentSession, sid)
        session.status = "running"
        stream._stream_finish(sid, "")
        db.commit()
        #: 会话还标着 running,但这一轮的流已经收尾:不能再拿旧 turn 给新卡背书。
        with pytest.raises(ConfirmationError):
            propose(
                db, _user(db), workspace_id=session.workspace_id, tool="browser_open",
                payload={"url": "https://example.com"}, session_id=sid, tool_call_id="call-3",
                require_live_turn=True,
            )


def test_回合收尾只作废本轮的卡() -> None:
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        old = ToolConfirmation(
            workspace_id=db.get(AgentSession, sid).workspace_id,
            session_id=sid,
            turn_id="turn-old",
            tool="browser_open",
            permission="edit",
            summary="旧卡",
            payload={},
            status="pending",
        )
        new = ToolConfirmation(
            workspace_id=old.workspace_id,
            session_id=sid,
            turn_id="turn-new",
            tool="browser_open",
            permission="edit",
            summary="新卡",
            payload={},
            status="pending",
        )
        db.add_all([old, new])
        db.commit()
        old_id, new_id = old.id, new.id

    with SessionLocal() as db:
        assert expire_session_cards(db, sid, EXPIRED, turn_id="turn-old") == 1
        db.commit()
        assert db.get(ToolConfirmation, old_id).status == EXPIRED
        assert db.get(ToolConfirmation, new_id).status == "pending"
