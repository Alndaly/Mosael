"""社区能力从应用里拿掉之后(2026-09-27):跑过接入社区那几条迁移的库,升级后不留任何痕迹。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.models import Job
from app.db.migrations import _migrate_drop_the_community_integration
from tests.util import fresh_client


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_接入社区时加的列和表_升级后都删掉_画板分享任务的记录也清掉() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    client.post("/api/workflows", json={"workspace_id": ws, "name": "出图", "description": ""})
    client.post("/api/entities", json={"workspace_id": ws, "kind": "prop", "name": "红伞"})
    #: 一台开发机跑过接入社区那几条迁移之后的样子。
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config ADD COLUMN community_url VARCHAR(500) NOT NULL DEFAULT 'https://mosael.com'"))
        conn.execute(text("ALTER TABLE boards ADD COLUMN board_key VARCHAR(64) NOT NULL DEFAULT 'k'"))
        conn.execute(text("ALTER TABLE workflows ADD COLUMN community_slug VARCHAR(160) NOT NULL DEFAULT ''"))
        conn.execute(text("ALTER TABLE entities ADD COLUMN community JSON NOT NULL DEFAULT '{}'"))
        conn.execute(text("CREATE TABLE community_accounts (user_id VARCHAR(64) PRIMARY KEY, refresh_token TEXT)"))
        conn.execute(text("CREATE TABLE board_shares (board_id VARCHAR(64) PRIMARY KEY, slug VARCHAR(160))"))
    engine.dispose()
    with SessionLocal() as db:
        db.add(Job(workspace_id=ws, kind="board_share", status="succeeded"))
        db.add(Job(workspace_id=ws, kind="generate_image", status="succeeded"))
        db.commit()

    _migrate_drop_the_community_integration()
    _migrate_drop_the_community_integration()  # 再跑一次什么都不做

    tables = set(inspect(engine).get_table_names())
    assert "community_accounts" not in tables and "board_shares" not in tables
    assert "community_url" not in _columns("deployment_config")
    assert "board_key" not in _columns("boards")
    assert "community_slug" not in _columns("workflows")
    assert "community" not in _columns("entities")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT kind FROM jobs")).scalars().all() == ["generate_image"], "别的任务留着"
    # 删列之后该在的都还在,接口照常。
    assert client.get(f"/api/boards/{board}", params={"workspace_id": ws}).status_code == 200
    assert len(client.get("/api/workflows", params={"workspace_id": ws}).json()) == 1
    assert len(client.get("/api/entities", params={"workspace_id": ws}).json()) == 1


def test_新装机上什么都不做() -> None:
    fresh_client()
    _migrate_drop_the_community_integration()
    assert "community_accounts" not in set(inspect(engine).get_table_names())
