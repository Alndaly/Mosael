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


def test_missing_card_capability_degrades_to_text_and_records_why(ctx, monkeypatch) -> None:
    """开发者后台没开交互卡片时,不能静默失败。

    这两个开关没有接口可配(事件订阅是后台配置项,改完还要重新发布应用),所以一键创建也代劳
    不了。能做的是撞上时降级成纯文本、把原因写进机器人状态,而不是让用户对着一张点了没反应的
    卡片猜 —— 更不能让确认本身建不出来。
    """
    from app.integrations.feishu import service

    client, ws, user_id, _ = ctx
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws, app_id="cli_x", app_secret="s")
        db.add(bot)
        db.commit()
        bot_id = bot.id

    sent: list[str] = []
    monkeypatch.setattr(
        service, "send_card",
        lambda *a, **k: (_ for _ in ()).throw(service.FeishuError("飞书发卡片失败: 200340")),
    )
    monkeypatch.setattr(service, "send_text", lambda bot, chat, text: sent.append(text))
    monkeypatch.setattr(service, "_feishu_origin", lambda db, sid: (db.get(FeishuBot, bot_id), "oc_chat"))

    cid = _make_confirmation(client, ws)  # 建卡片时会触发推送

    assert sent, "卡片发不出去时应当退成纯文本,而不是什么都不发"
    assert "等待确认" in sent[0] and "card.action.trigger" in sent[0]
    assert _status(cid) == "pending", "推送失败不该影响确认本身"
    with SessionLocal() as db:
        assert service.CARD_CAPABILITY_ERROR in (db.get(FeishuBot, bot_id).status_detail or "")


def test_card_send_failure_never_breaks_confirmation(ctx, monkeypatch) -> None:
    """连纯文本都发不出去时,确认仍然要建得出来(退化回桌面端确认中心兜底)。"""
    from app.integrations.feishu import service

    client, ws, _, _ = ctx
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws, app_id="cli_y", app_secret="s")
        db.add(bot)
        db.commit()
        bot_id = bot.id

    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("网络炸了"))  # noqa: E731
    monkeypatch.setattr(service, "send_card", boom)
    monkeypatch.setattr(service, "send_text", boom)
    monkeypatch.setattr(service, "_feishu_origin", lambda db, sid: (db.get(FeishuBot, bot_id), "oc_chat"))

    cid = _make_confirmation(client, ws)
    assert _status(cid) == "pending"
