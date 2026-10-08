"""「每次都问」是确认卡工具上的一个声明(`ConfirmableTool.always_asks`),不是按名字特判(ADR 0043 拍板 2)。

声明了它的卡,任何一种口子都放不过:「本会话始终允许」、bypass、auto 档的 edit 直放、放行准则、判断者。这里用一个
临时登记的假工具钉住内核这一半 —— 不认识任何具体工具;改技能那几个工具各自声明了它,见 test_agent_manages_skills。

另一半是批准时的开关(`ConfirmableTool.choices`):批的人在卡上拨的那几个布尔值,只认声明过的键。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import AgentSession, ToolConfirmation, User, Workspace
from app.domain.agent import rules
from app.domain.agent.autopilot import wait_for_idle_autopilot
from app.domain.agent.confirmable import registry
from app.domain.agent.confirmable.registry import ConfirmableTool
from app.domain.agent.proposals import propose
from tests.util import fresh_client

FAKE = "zz_always_asks_probe"
executed: list[dict[str, Any]] = []


def _execute(db, confirmation, actor) -> dict[str, Any]:
    executed.append(dict(confirmation.payload))
    return {"ok": True}


@pytest.fixture
def probe(monkeypatch):
    """一张声明了「每次都问」、带一个开关的卡。只在这条测试里登记,测完自动撤掉。"""
    executed.clear()
    spec = ConfirmableTool(
        name=FAKE, permission="edit", cost="none", always_asks=True, choices=("enable",),
        summarize=lambda db, payload: ("confirm_noteUntitled", {}), execute=_execute, writes=(),
    )
    monkeypatch.setitem(registry._TOOLS, FAKE, spec)
    return spec


def _chat(client) -> tuple[str, str]:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace, "title": "T"}).json()["id"]
    return workspace, session


def _open(workspace: str, session: str, payload: dict | None = None) -> str:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        card = propose(db, user, workspace_id=workspace, tool=FAKE, payload=payload or {"enable": True}, session_id=session)
        db.commit()
        card_id = card.id
    wait_for_idle_autopilot()
    return card_id


def _card(card_id: str) -> ToolConfirmation:
    with SessionLocal() as db:
        card = db.get(ToolConfirmation, card_id)
        db.expunge(card)
        return card


def test_声明和自动放行的口子互斥() -> None:
    noop = dict(summarize=lambda db, payload: ("", {}), execute=_execute, writes=())
    with pytest.raises(ValueError):
        ConfirmableTool(name="x", permission="edit", cost="none", always_asks=True, gate="g", gate_label="G", **noop)
    with pytest.raises(ValueError):
        ConfirmableTool(name="x", permission="edit", cost="none", always_asks=True, needs_card=lambda db, p: False, **noop)


def test_bypass_档也不放过(probe) -> None:
    client = fresh_client()
    workspace, session = _chat(client)
    assert client.patch(f"/api/agent/sessions/{session}", json={"permission_mode": "bypass"}).status_code == 200

    card = _card(_open(workspace, session))

    assert card.status == "pending" and executed == []
    assert card.decision_detail == {"reason": "always-asks"}


def test_auto_档的_edit_直放和放行准则都不放过(probe) -> None:
    client = fresh_client()
    workspace, session = _chat(client)
    assert client.patch(f"/api/agent/sessions/{session}", json={"permission_mode": "auto"}).status_code == 200
    with SessionLocal() as db:
        db.get(Workspace, workspace).autopilot_rules = {key: "always" for key in rules.gates()}
        db.commit()

    assert _card(_open(workspace, session)).status == "pending"
    assert rules.evaluate(FAKE, {}, {key: "always" for key in rules.gates()}).denied, "没有可配置的放行判据"


def test_本会话始终允许_加不进去_库里硬塞的也不生效(probe) -> None:
    client = fresh_client()
    workspace, session = _chat(client)
    refused = client.patch(f"/api/agent/sessions/{session}", json={"auto_allow_tools": [{"tool": FAKE, "permission": "edit"}]})
    assert refused.status_code == 422, refused.text
    assert FAKE in refused.text

    with SessionLocal() as db:
        row = db.get(AgentSession, session)
        row.auto_allow_tools = [{"tool": FAKE, "permission": "edit"}]
        row.mode_set_by = db.query(User).filter(User.username == "tester").one().id
        db.commit()
    assert _card(_open(workspace, session)).status == "pending", "绕过接口直接写进库里的白名单也放不过它"


def test_卡上说明它每次都问_带着开关的缺省值(probe) -> None:
    client = fresh_client()
    workspace, session = _chat(client)
    card_id = _open(workspace, session, {"enable": True})

    listed = client.get(f"/api/confirmations?workspace_id={workspace}&session_id={session}").json()
    out = next(one for one in listed if one["id"] == card_id)
    assert out["always_asks"] is True
    assert out["choices"] == {"enable": True}


def test_批准时拨的开关写进_payload_执行体看得到(probe) -> None:
    client = fresh_client()
    workspace, session = _chat(client)
    card_id = _open(workspace, session, {"enable": True})

    approved = client.post(f"/api/confirmations/{card_id}/approve", json={"choices": {"enable": False}})

    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    assert approved.json()["choices"] == {"enable": False}
    assert executed == [{"enable": False}]


def test_没声明的键_批准不了_卡还在等(probe) -> None:
    client = fresh_client()
    workspace, session = _chat(client)
    card_id = _open(workspace, session, {"enable": True})

    refused = client.post(f"/api/confirmations/{card_id}/approve", json={"choices": {"note_id": True}})
    assert refused.status_code == 409, refused.text
    refused = client.post(f"/api/confirmations/{card_id}/approve", json={"choices": {"enable": "yes"}})
    assert refused.status_code == 422, refused.text

    assert _card(card_id).status == "pending" and executed == []
    assert client.post(f"/api/confirmations/{card_id}/approve").json()["status"] == "executed", "不带请求体照缺省批"
    assert executed == [{"enable": True}]
