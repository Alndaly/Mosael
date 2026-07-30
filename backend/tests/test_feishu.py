from __future__ import annotations

import time

from app.ai.agent.adapters import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentSession
from app.integrations.feishu import service
from tests.util import fresh_client


def test_extract_text_strips_mentions() -> None:
    assert service.extract_text('{"text": "@_user_1 @_user_2 帮我看看素材"}') == "帮我看看素材"
    assert service.extract_text('{"text": "普通消息"}') == "普通消息"
    assert service.extract_text("not-json") == ""


def test_seen_recently_dedupes() -> None:
    message_id = f"m-{time.time()}"
    assert service.seen_recently(message_id) is False
    assert service.seen_recently(message_id) is True


def test_bot_crud_and_permissions() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    created = client.post(
        "/api/feishu/bots",
        json={"workspace_id": ws["id"], "app_id": "cli_a1", "app_secret": "s3cret", "capability": "readonly"},
    ).json()
    assert created["capability"] == "readonly"
    assert "app_secret" not in created  # secrets never serialize

    listed = client.get(f"/api/feishu/bots?workspace_id={ws['id']}").json()
    assert len(listed) == 1

    updated = client.patch(f"/api/feishu/bots/{created['id']}", json={"capability": "editor", "enabled": False}).json()
    assert updated["capability"] == "editor"
    assert updated["enabled"] is False

    assert client.delete(f"/api/feishu/bots/{created['id']}").status_code == 204


def test_handle_incoming_routes_to_agent_and_replies(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots",
        json={"workspace_id": ws["id"], "app_id": "cli_a2", "app_secret": "s3cret"},
    ).json()
    # stop_connection is a no-op in tests (start failed w/o real creds), status irrelevant here

    # The sender must be bound to a member first — the bot acts with that member's perms.
    me = client.get("/api/auth/me").json()
    with SessionLocal() as db:
        code, _ = service.issue_bind_code(db, ws["id"], me["id"])
        assert service._redeem_bind_code(db, ws["id"], "ou_sender", code) is not None

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: TurnResult(text="已查看,共 2 个素材"))
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append((chat_id, text)))

    service.handle_incoming(bot["id"], "oc_chat_1", "看看素材", "msg-1", "ou_sender")

    assert sent == [("oc_chat_1", "已查看,共 2 个素材")]
    with SessionLocal() as db:
        session = db.query(AgentSession).filter_by(external_key=f"feishu:{bot['id']}:oc_chat_1").one()
        assert session.origin == "feishu"
        assert session.status == "idle"
        roles = [m.role for m in session.messages]
        assert roles == ["user", "assistant"]

    # duplicate message id is dropped
    service.handle_incoming(bot["id"], "oc_chat_1", "看看素材", "msg-1", "ou_sender")
    assert len(sent) == 1


def test_handle_incoming_unbound_sender_refused(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots", json={"workspace_id": ws["id"], "app_id": "cli_a4", "app_secret": "s3cret"}
    ).json()
    ran: list[bool] = []
    sent: list[str] = []
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: ran.append(True))
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append(text))

    service.handle_incoming(bot["id"], "oc_chat_x", "偷偷改点东西", "msg-x", "ou_intruder")

    assert ran == []  # the agent never ran for an unbound sender
    assert sent and "绑定" in sent[0]


def test_handle_incoming_adapter_error_still_replies(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots",
        json={"workspace_id": ws["id"], "app_id": "cli_a3", "app_secret": "s3cret"},
    ).json()

    sent: list[str] = []
    from app.ai.agent.adapters import AdapterError

    def boom(*args, **kwargs):
        raise AdapterError("cli exploded")

    me = client.get("/api/auth/me").json()
    with SessionLocal() as db:
        code, _ = service.issue_bind_code(db, ws["id"], me["id"])
        service._redeem_bind_code(db, ws["id"], "ou_sender2", code)

    monkeypatch.setattr(service, "run_turn", boom)
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append(text))

    service.handle_incoming(bot["id"], "oc_chat_2", "hi", "msg-2", "ou_sender2")
    assert sent and "失败" in sent[0]
