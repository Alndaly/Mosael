from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import FeishuBot
from app.integrations.feishu import service
from tests.util import fresh_client, second_client


def test_unbound_sender_denied_and_bind_code_flow() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    me = client.get("/api/auth/me").json()
    with SessionLocal() as db:
        # An unbound Feishu sender resolves to nobody → handle_incoming refuses (no owner action).
        assert service._resolve_sender(db, ws["id"], "ou_stranger") is None

        # Member issues a one-time code; a Feishu sender redeems it → bound to that member.
        code, _ = service.issue_bind_code(db, ws["id"], me["id"])
        redeemed = service._redeem_bind_code(db, ws["id"], "ou_alice", code)
        assert redeemed is not None and redeemed.id == me["id"]

        # That open_id now resolves to the member; the code is one-time.
        assert service._resolve_sender(db, ws["id"], "ou_alice").id == me["id"]
        assert service._redeem_bind_code(db, ws["id"], "ou_bob", code) is None
        # A different, still-unbound sender is still denied.
        assert service._resolve_sender(db, ws["id"], "ou_bob") is None


def test_bind_code_route_requires_membership() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws["id"], app_id="a", app_secret="s")
        db.add(bot)
        db.commit()
        bot_id = bot.id

    ok = client.post(f"/api/feishu/bots/{bot_id}/bind-code")
    assert ok.status_code == 200 and len(ok.json()["code"]) >= 4

    stranger = second_client("stranger")
    assert stranger.post(f"/api/feishu/bots/{bot_id}/bind-code").status_code == 404  # non-member → hidden
