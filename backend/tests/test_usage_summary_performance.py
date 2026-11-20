"""统计聚合只取计量与费用字段,不加载用于审计/回填的服务商完整回包。"""

from __future__ import annotations

from sqlalchemy import event

from app.core.db import SessionLocal, engine
from app.domain.billing.usage import record_usage, summarize_usage
from tests.util import fresh_client


def test_统计聚合不读取_raw_usage() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        record_usage(
            db,
            user_id=None,
            workspace_id=workspace,
            capability="image",
            operation="generate",
            idempotency_key="usage-raw",
            units={"input_tokens": 10, "output_tokens": 5},
            raw_usage={"provider_payload": "x" * 100_000},
        )
        db.commit()

    statements: list[str] = []

    def capture(_conn, _cursor, sql: str, _parameters, _context, _executemany) -> None:
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with SessionLocal() as db:
            summarize_usage(db, workspace_id=workspace)
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    queries = [
        sql for sql in statements
        if sql.lstrip().upper().startswith("SELECT") and "FROM provider_usage_events" in sql
    ]
    assert queries
    assert all("provider_usage_events.raw_usage" not in sql for sql in queries), queries
