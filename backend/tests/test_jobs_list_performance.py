"""任务列表的性能契约:大历史表按时间索引读取,列表不加载只在详情里使用的 result。"""

from __future__ import annotations

from sqlalchemy import event, text

from app.core.db import SessionLocal, engine
from app.db.models import Job
from tests.util import fresh_client


def test_旧库补最近任务索引_按时间列表不再临时排序() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_jobs_workspace_created_id"))

    from app.db.migrations import _migrate_jobs_list_recent_index

    _migrate_jobs_list_recent_index()
    _migrate_jobs_list_recent_index()  # 幂等:重复启动不会重建或报错。

    with engine.begin() as conn:
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))}
        plan = conn.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT * FROM jobs WHERE workspace_id = :workspace "
                "ORDER BY created_at DESC, id DESC LIMIT 200"
            ),
            {"workspace": workspace},
        ).fetchall()
    details = [row[-1] for row in plan]
    assert "idx_jobs_workspace_created_id" in indexes
    assert any("idx_jobs_workspace_created_id" in detail for detail in details), details
    assert not any("TEMP B-TREE" in detail for detail in details), details


def test_任务列表和面板都不读取只在详情里使用的_result() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(Job(
            workspace_id=workspace,
            kind="workflow",
            status="succeeded",
            message="done",
            payload={"input": "small"},
            result={"large": "x" * 100_000},
        ))
        db.commit()

    statements: list[str] = []

    def capture(_conn, _cursor, sql: str, _parameters, _context, _executemany) -> None:
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        for url in (f"/api/jobs?workspace_id={workspace}", f"/api/jobs/center?workspace_id={workspace}"):
            response = client.get(url)
            assert response.status_code == 200, response.text
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    queries = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT") and "FROM jobs" in sql]
    assert queries
    assert all("jobs.result" not in sql for sql in queries), queries


def test_最近任务查询只计算一次隐藏任务集合_两条任务查询复用() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    statements: list[str] = []

    def capture(_conn, _cursor, sql: str, _parameters, _context, _executemany) -> None:
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get(f"/api/jobs?workspace_id={workspace}")
        assert response.status_code == 200, response.text
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    hidden_queries = [sql for sql in selects if "FROM generation_jobs" in sql]
    job_queries = [sql for sql in selects if "FROM jobs" in sql]
    assert len(hidden_queries) == 1, selects
    assert len(job_queries) == 2, selects
    assert all("generation_jobs" not in sql and "generation_sessions" not in sql for sql in job_queries), job_queries
    assert all("jobs.status NOT IN" not in sql for sql in job_queries), job_queries
