"""`agent_sessions.working_set` 迁移:老库补列,旧行保留,重跑不再改。

这是 CI 的迁移棘轮要求的那条点名测试:既能证明旧形状真的被补成新形状,也证明第二次跑
不会覆盖已经写入的关注上下文。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_agent_sessions_working_set
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.begin() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}


def test_working_set_is_added_to_old_rows_and_rerun_is_a_noop() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(
        "/api/agent/sessions",
        json={"workspace_id": workspace, "home": {"kind": "studio"}},
    )
    assert created.status_code == 200, created.text
    session_id = created.json()["id"]

    #: 升级前的形状:没有 working_set 列,旧行照旧在。
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions DROP COLUMN working_set"))
    assert "working_set" not in _columns()

    _migrate_agent_sessions_working_set()

    assert "working_set" in _columns()
    with engine.begin() as conn:
        stored = conn.execute(
            text("SELECT working_set FROM agent_sessions WHERE id = :id"), {"id": session_id}
        ).scalar_one()
    assert json.loads(stored) == {}

    #: 已经有值的一行,再跑一次迁移不能被重置。
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE agent_sessions SET working_set = :working WHERE id = :id"),
            {"working": json.dumps({"project_id": "p1", "surface": "editor"}), "id": session_id},
        )
    _migrate_agent_sessions_working_set()
    with engine.begin() as conn:
        stored = conn.execute(
            text("SELECT working_set FROM agent_sessions WHERE id = :id"), {"id": session_id}
        ).scalar_one()
    assert json.loads(stored) == {"project_id": "p1", "surface": "editor"}
