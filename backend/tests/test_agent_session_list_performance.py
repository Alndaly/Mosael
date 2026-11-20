"""会话列表只读摘要字段;pi 的完整运行状态只在执行/详情路径加载。"""

from __future__ import annotations

from sqlalchemy import event

from app.core.db import SessionLocal, engine
from app.db.models import AgentSession
from tests.util import fresh_client


def test_会话列表不读取_adapter_state() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post(
        "/api/agent/sessions",
        json={"workspace_id": workspace, "home": {"kind": "studio"}},
    ).json()
    with SessionLocal() as db:
        session = db.get(AgentSession, created["id"])
        session.adapter_state = {"messages": [{"role": "assistant", "content": "x" * 100_000}]}
        db.commit()

    statements: list[str] = []

    def capture(_conn, _cursor, sql: str, _parameters, _context, _executemany) -> None:
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/agent/sessions?workspace_id={workspace}")
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    queries = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("SELECT") and "FROM agent_sessions" in sql
    ]
    assert queries
    assert all("agent_sessions.adapter_state" not in sql for sql in queries), queries
