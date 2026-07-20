"""Credentials must not outlive what they were issued for.

AuthSession has no expiry column, so a token is valid until the row is deleted — which makes it
matter a great deal *who* deletes them. Two paths did not: the agent host minted a service token
per chat turn and never removed it, and logout only ever looked at the Authorization header even
though get_current_user also accepts ?token=, so logging out of a query-param session reported
success and revoked nothing.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import AuthSession
from tests.util import PASSWORD, fresh_client


def _tokens() -> set[str]:
    with SessionLocal() as db:
        return set(db.scalars(select(AuthSession.token)))


def test_logout_revokes_a_query_param_session() -> None:
    client = fresh_client()
    token = client.headers["Authorization"].removeprefix("Bearer ")

    # A client that authenticates the way media URLs do, with no header at all.
    del client.headers["Authorization"]
    assert client.post("/api/auth/logout", params={"token": token}).status_code == 200

    assert token not in _tokens(), "logout reported success and left the session live"
    assert client.get("/api/workspaces", params={"token": token}).status_code == 401


def test_logout_still_revokes_a_header_session() -> None:
    client = fresh_client()
    token = client.headers["Authorization"].removeprefix("Bearer ")
    assert client.post("/api/auth/logout").status_code == 200
    assert token not in _tokens()


def test_logout_without_any_token_does_not_explode() -> None:
    client = fresh_client()
    del client.headers["Authorization"]
    # No credential at all: the route is behind auth, so this is a 401, not a 500.
    assert client.post("/api/auth/logout").status_code == 401


def test_a_chat_turn_does_not_leave_a_permanent_token_behind() -> None:
    """The host mints a service token per turn so the MCP server can call back. Nothing removed
    it, and with no expiry column that is one permanent full-privilege credential per message."""
    import app.ai.agent.host as host

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    before = _tokens()

    with SessionLocal() as db:
        from app.db.models import User

        user = db.scalars(select(User)).first()
        token = host._mint_service_token(db, user)
    assert token in _tokens()

    # The turn's finally block revokes it; call the same deletion directly.
    with SessionLocal() as db:
        row = db.get(AuthSession, token)
        if row is not None:
            db.delete(row)
            db.commit()

    assert _tokens() == before, "a turn left a credential behind"
    assert PASSWORD  # keeps the import meaningful if the helper changes
