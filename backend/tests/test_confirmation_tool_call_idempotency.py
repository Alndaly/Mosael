"""同一次工具调用的确认卡创建与执行都必须幂等。"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import ToolConfirmation, User
from app.domain.agent.confirmable import registry
from app.domain.agent.confirmable.registry import ConfirmableTool
from app.domain.agent.confirmations import authorize_and_approve
from app.domain.agent.proposals import propose
from tests.util import fresh_client


TOOL = "zz_tool_call_idempotency_probe"
executed: list[dict[str, Any]] = []


@pytest.fixture
def probe(monkeypatch):
    executed.clear()
    monkeypatch.setitem(
        registry._TOOLS,
        TOOL,
        ConfirmableTool(
            name=TOOL,
            permission="edit",
            cost="none",
            always_asks=True,
            summarize=lambda db, payload: ("confirm_noteUntitled", {}),
            execute=lambda db, confirmation, actor: executed.append(dict(confirmation.payload)) or {"ok": True},
            writes=(),
        ),
    )


def test_同一tool_call_id重试复用原卡_批准后也不重复执行(probe) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post(
        "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace, "title": "T"}
    ).json()["id"]

    def submit():
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            card = propose(
                db,
                user,
                workspace_id=workspace,
                session_id=session,
                tool_call_id="call-1",
                tool=TOOL,
                payload={"value": 1},
            )
            db.commit()
            return card.id, card.status

    first = submit()
    assert submit() == first, "等待确认时重试不能再开一张卡"

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        authorize_and_approve(db, user, db.get(ToolConfirmation, first[0]))
        db.commit()
    assert len(executed) == 1

    assert submit() == (first[0], "executed"), "执行完成后的重试要返回原结果，不能再执行"
    assert len(executed) == 1
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).filter(ToolConfirmation.session_id == session).count() == 1


def test_并发开同一tool_call_id也返回同一张卡(probe, monkeypatch) -> None:
    """两个请求都穿过首次查询时，唯一索引冲突要转成读取原卡，不能把 500 交给调用方。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post(
        "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace, "title": "T"}
    ).json()["id"]
    from concurrent.futures import ThreadPoolExecutor
    import threading

    from app.domain.agent import proposals

    barrier = threading.Barrier(2)
    original = proposals._for_tool_call

    calls = 0

    def synchronized_lookup(*args, **kwargs):
        nonlocal calls
        calls += 1
        found = original(*args, **kwargs)
        if calls <= 2:
            barrier.wait()
        return found

    monkeypatch.setattr(proposals, "_for_tool_call", synchronized_lookup)

    def submit():
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            card = propose(
                db, user, workspace_id=workspace, session_id=session, tool_call_id="call-race",
                tool=TOOL, payload={"value": 1},
            )
            db.commit()
            return card.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: submit(), range(2)))
    assert ids[0] == ids[1]
    with SessionLocal() as db:
        assert db.query(ToolConfirmation).filter(ToolConfirmation.session_id == session).count() == 1
