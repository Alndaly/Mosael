"""技能索引行补「智能体在哪次对话里建的」那一列(ADR 0043,`_migrate_agent_skills_remember_the_drafting_session`)。

老库里的行都是人在设置里建、导入、存成的 —— 新列落成 NULL 就是它们的真实情况;再跑一次什么都不做;
那次对话删了,链接跟着回到 NULL(外键 ON DELETE SET NULL,迁移加的列也一样)。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(agent_skills)"))}


def _old_table(workspace_id: str) -> None:
    """ADR 0040 时的那张表(没有 agent_session_id),和一行人在设置里建的。"""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE agent_skills"))
        conn.execute(text(
            "CREATE TABLE agent_skills (id VARCHAR(64) PRIMARY KEY, "
            "workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, source VARCHAR(16) NOT NULL, "
            "package_id VARCHAR(160) NOT NULL, name VARCHAR(64) NOT NULL, enabled BOOLEAN NOT NULL, "
            "origin VARCHAR(24) NOT NULL, imported_from VARCHAR(255) NOT NULL, created_by VARCHAR(64), "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, "
            "CONSTRAINT uq_agent_skills_identity UNIQUE (workspace_id, source, package_id, name))"))
        conn.execute(text(
            "INSERT INTO agent_skills VALUES ('s1', :ws, 'workspace', '', 'brand-rules', 1, 'created', '', NULL, "
            "'2026-10-06 00:00:00', '2026-10-06 00:00:00')"), {"ws": workspace_id})


def test_老库的技能行补上_agent_session_id_老行是_NULL_再跑一次不报错() -> None:
    from app.db.migrations import _migrate_agent_skills_remember_the_drafting_session

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _old_table(workspace)
    assert "agent_session_id" not in _columns()

    _migrate_agent_skills_remember_the_drafting_session()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT name, origin, enabled, agent_session_id FROM agent_skills")).one()
    assert tuple(row) == ("brand-rules", "created", 1, None)
    _migrate_agent_skills_remember_the_drafting_session()  # 再跑一次不报 duplicate column
    assert "agent_session_id" in _columns()


def test_迁移加的列也跟着对话删除回到_NULL() -> None:
    from app.db.migrations import _migrate_agent_skills_remember_the_drafting_session

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace, "title": "T"}).json()["id"]
    _old_table(workspace)
    _migrate_agent_skills_remember_the_drafting_session()
    with engine.begin() as conn:
        conn.execute(text("UPDATE agent_skills SET origin = 'agent', agent_session_id = :s"), {"s": session})

    assert client.delete(f"/api/agent/sessions/{session}").status_code in (200, 204)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT origin, agent_session_id FROM agent_skills")).one() == ("agent", None)


def test_没有技能表的老库_不建半张() -> None:
    from app.db.migrations import _migrate_agent_skills_remember_the_drafting_session

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE agent_skills"))
    _migrate_agent_skills_remember_the_drafting_session()
    assert _columns() == set()
