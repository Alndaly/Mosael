"""`agent_sessions.plan_id` 迁移:老库补列,旧行保留,重跑不再改。"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_agent_sessions_plan_id
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.begin() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}


def test_plan_id_is_added_and_rerun_is_a_noop() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(
        "/api/agent/sessions",
        json={"workspace_id": workspace, "home": {"kind": "studio"}},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions DROP COLUMN plan_id"))
    assert "plan_id" not in _columns()

    _migrate_agent_sessions_plan_id()

    assert "plan_id" in _columns()
    with engine.begin() as conn:
        stored = conn.execute(
            text("SELECT plan_id FROM agent_sessions WHERE id = :id"), {"id": session_id}
        ).scalar_one()
    assert stored is None

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_sessions SET plan_id = 'keep-me' WHERE id = :id"), {"id": session_id}
        )
    _migrate_agent_sessions_plan_id()
    with engine.begin() as conn:
        stored = conn.execute(
            text("SELECT plan_id FROM agent_sessions WHERE id = :id"), {"id": session_id}
        ).scalar_one()
    assert stored == "keep-me"
