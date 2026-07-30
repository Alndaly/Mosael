from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import FeishuBinding, FeishuBot, ToolConfirmation, User, WorkspaceMember
from app.integrations.feishu import cards
from app.integrations.feishu.service import handle_card_action
from tests.util import fresh_client

"""飞书确认卡的**授权**。

卡片挂在群里,群里谁都看得见;看得见不等于能批。授权走的是和发消息同一条路径
(open_id → feishu_bindings → 仍是工作区成员),所以这里逐条钉住那条路径的每个出口。
"""

OTHER_OPEN_ID = "ou_someone_else"


def _bind(workspace_id: str, open_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        db.add(FeishuBinding(workspace_id=workspace_id, open_id=open_id, user_id=user_id))
        db.commit()


def _make_confirmation(client, workspace_id: str) -> str:
    """建一条待确认。用 set_clip_texts 之外最简单的工具,避免牵扯素材/序列。"""
    res = client.post(
        "/api/confirmations",
        json={
            "workspace_id": workspace_id,
            "tool": "create_workflow",
            "requested_by": "pi",
            "payload": {"name": "卡片测试流", "graph": {"nodes": [], "edges": []}},
        },
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _status(confirmation_id: str) -> str:
    with SessionLocal() as db:
        row = db.get(ToolConfirmation, confirmation_id)
        return row.status if row else "gone"


@pytest.fixture
def ctx():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        me = db.scalars(__import__("sqlalchemy").select(User)).first()
        user_id, username = me.id, me.username
    return client, ws["id"], user_id, username


def test_unbound_clicker_is_refused_and_card_stays_pending(ctx) -> None:
    """没绑定账号的人点了不算数 —— 这是「授权建立在账号体系上」的底线。"""
    client, ws, _, _ = ctx
    cid = _make_confirmation(client, ws)
    out = handle_card_action(OTHER_OPEN_ID, {"action": cards.ACTION_APPROVE, "confirmation_id": cid})
    assert "toast" in out and "绑定" in out["toast"]["content"]
    assert _status(cid) == "pending", "未绑定者的点击不该改变卡片状态"


def test_no_open_id_is_refused(ctx) -> None:
    client, ws, _, _ = ctx
    cid = _make_confirmation(client, ws)
    out = handle_card_action("", {"action": cards.ACTION_APPROVE, "confirmation_id": cid})
    assert "toast" in out
    assert _status(cid) == "pending"


def test_bound_member_can_approve(ctx) -> None:
    client, ws, user_id, username = ctx
    _bind(ws, OTHER_OPEN_ID, user_id)
    cid = _make_confirmation(client, ws)
    out = handle_card_action(OTHER_OPEN_ID, {"action": cards.ACTION_APPROVE, "confirmation_id": cid})
    assert "card" in out, out
    # 就地替换成已决卡,且**不再带按钮** —— 否则同一张卡会被反复点。
    rendered = str(out["card"]["data"])
    assert "已同意" in rendered and username in rendered
    assert "button" not in rendered
    # 批准即执行,终态是 executed(approve_confirmation 批完就跑),不是停在 approved。
    assert _status(cid) == "executed"


def test_bound_member_can_reject(ctx) -> None:
    client, ws, user_id, _ = ctx
    _bind(ws, OTHER_OPEN_ID, user_id)
    cid = _make_confirmation(client, ws)
    out = handle_card_action(OTHER_OPEN_ID, {"action": cards.ACTION_REJECT, "confirmation_id": cid})
    assert "card" in out and "已拒绝" in str(out["card"]["data"])
    assert _status(cid) == "rejected"


def test_binding_survives_only_while_still_a_member(ctx) -> None:
    """绑过但已被移出工作区 → 拒绝。绑定不是永久通行证。"""
    client, ws, user_id, _ = ctx
    _bind(ws, OTHER_OPEN_ID, user_id)
    cid = _make_confirmation(client, ws)
    with SessionLocal() as db:
        for row in db.scalars(
            __import__("sqlalchemy").select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws)
        ):
            db.delete(row)
        db.commit()
    out = handle_card_action(OTHER_OPEN_ID, {"action": cards.ACTION_APPROVE, "confirmation_id": cid})
    assert "toast" in out
    assert _status(cid) == "pending"


def test_settled_card_cannot_be_clicked_again(ctx) -> None:
    client, ws, user_id, _ = ctx
    _bind(ws, OTHER_OPEN_ID, user_id)
    cid = _make_confirmation(client, ws)
    handle_card_action(OTHER_OPEN_ID, {"action": cards.ACTION_REJECT, "confirmation_id": cid})
    again = handle_card_action(OTHER_OPEN_ID, {"action": cards.ACTION_APPROVE, "confirmation_id": cid})
    assert "toast" in again and "处理过" in again["toast"]["content"]
    assert _status(cid) == "rejected", "重复点击不该翻转已决状态"


def test_garbage_payloads_do_not_crash(ctx) -> None:
    """value 来自外部,不可信也不该让 worker 崩。"""
    client, ws, user_id, _ = ctx
    _bind(ws, OTHER_OPEN_ID, user_id)
    for value in ({}, {"action": "confirm.approve"}, {"action": "rm -rf", "confirmation_id": "x"},
                  {"confirmation_id": "does-not-exist", "action": cards.ACTION_APPROVE}):
        out = handle_card_action(OTHER_OPEN_ID, value)
        assert "toast" in out, value


def test_pending_card_has_both_buttons() -> None:
    card = cards.confirmation_card(confirmation_id="c1", tool="create_workflow", summary="建一条流", requested_by="pi")
    actions = [e for e in card["elements"] if e.get("tag") == "action"][0]["actions"]
    assert {a["value"]["action"] for a in actions} == {cards.ACTION_APPROVE, cards.ACTION_REJECT}
    assert all(a["value"]["confirmation_id"] == "c1" for a in actions)
