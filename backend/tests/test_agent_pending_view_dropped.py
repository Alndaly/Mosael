"""智能体带用户跳页(`open_view`)撤掉之后(ADR 0060),`agent_sessions` 上记跳转意图的两列跟着删掉。

钉的是迁移 `_drop_agent_pending_view`:老形状的库(带 `pending_view`、`pending_view_at`,还有一段对话正挂着一次没消费的
跳转)升级之后两列没了,对话和消息一样不少、别的列原样;再跑一遍什么都不变;它排在重建这张表之前 —— 重建的守卫认不出
模型上没有的列就拒绝动手。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import AgentMessage
from tests.util import fresh_client

DROPPED = {"pending_view", "pending_view_at"}


def _old_library() -> None:
    """两段对话,一段说过话、挂着一次没消费的跳转;表上补回那两列 —— 撤掉之前的样子。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sessions = []
    for title in ("找素材", "排发布"):
        created = client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": {"kind": "studio"}, "title": title})
        assert created.status_code == 200, created.text
        sessions.append(created.json()["id"])
    with SessionLocal() as db:
        db.add(AgentMessage(id="asked", session_id=sessions[0], role="user", content="带我去素材库", payload={}))
        db.add(AgentMessage(id="answered", session_id=sessions[0], role="assistant", content="好", payload={}))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN pending_view VARCHAR(96) NOT NULL DEFAULT ''"))
        conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN pending_view_at DATETIME"))
        conn.execute(
            text("UPDATE agent_sessions SET pending_view = 'media', pending_view_at = '2026-10-13 08:00:00' WHERE id = :id"),
            {"id": sessions[0]},
        )


def _columns() -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}


def _snapshot() -> dict[str, Any]:
    """除了要删的两列,每一行的每一列;外加消息。"""
    kept = sorted(_columns() - DROPPED)
    with engine.connect() as conn:
        sessions = conn.execute(text(f"SELECT {', '.join(kept)} FROM agent_sessions ORDER BY id")).all()
        messages = conn.execute(text("SELECT id, session_id, content FROM agent_messages ORDER BY id")).all()
    return {"sessions": [dict(zip(kept, row)) for row in sessions], "messages": messages}
