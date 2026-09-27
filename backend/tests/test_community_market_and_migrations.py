"""插件市场的「社区」来源(ADR 0026 §4),以及社区这一轮带来的几条迁移(含资产记下社区来源,ADR 0027 §4)。"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import (
    _migrate_boards_get_a_board_key,
    _migrate_deployment_community_url,
    _migrate_entities_remember_community,
    _migrate_workflows_remember_community_slug,
)
from app.domain import deployment
from app.domain.plugins import registry as market
from tests.community_fake import ORIGIN, install
from tests.util import fresh_client

COMMUNITY_ENTRY = {
    "id": "dev.someone.cool", "name": "好用的插件", "version": "0.3.0", "author": "someone",
    "download": "/api/community/v1/plugins/cool/download", "permissions": ["network:x"],
    "tools": [{"name": "go", "description": "跑", "effects": "read"}],
    "bundled": True,
}


def test_社区来源_单独一栏_标出来源_下载地址补全(monkeypatch) -> None:
    fake, client, _clock = install(monkeypatch)
    asked: list[str] = []

    def fetch(url: str) -> list[dict]:
        asked.append(url)
        return [dict(COMMUNITY_ENTRY)] if "community" in url else [{"id": "dev.mosael.official", "version": "1.0.0"}]

    monkeypatch.setattr(market, "fetch_index", fetch)
    community = client.get("/api/plugins/market", params={"source": "community"}).json()
    assert asked == [f"{ORIGIN}/api/community/v1/plugins/index.json"]
    assert community["index_error"] == ""
    [entry] = community["plugins"]
    assert entry["source"] == "community"
    assert entry["download"] == f"{ORIGIN}/api/community/v1/plugins/cool/download"
    # 社区条目不会是「内置」—— 索引里写了也不认。
    assert entry["bundled"] is False and entry["installed"] is False

    official = client.get("/api/plugins/market").json()
    assert "dev.someone.cool" not in {one["id"] for one in official["plugins"]}
    assert {one["source"] for one in official["plugins"]} == {"official"}


def test_社区来源_没配社区时说清楚(monkeypatch) -> None:
    _fake, client, _clock = install(monkeypatch)
    client.put("/api/admin/community", json={"url": ""})
    answer = client.get("/api/plugins/market", params={"source": "community"}).json()
    assert answer["plugins"] == [] and "社区地址" in answer["index_error"]


def _drop_column(table: str, column: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
    engine.dispose()


def _columns(table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_老部署补上社区地址_默认就是官网() -> None:
    fresh_client()
    with SessionLocal() as db:
        deployment.open_registration(db)
        db.commit()
    _drop_column("deployment_config", "community_url")
    _migrate_deployment_community_url()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT community_url FROM deployment_config")).scalars().all() == ["https://mosael.com"]
    _migrate_deployment_community_url()
    assert "community_url" in _columns("deployment_config")


def test_老画板逐张补一个不同的_board_key() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    for name in ("一", "二", "三"):
        client.post("/api/boards", json={"workspace_id": ws, "name": name})
    _drop_column("boards", "board_key")
    _migrate_boards_get_a_board_key()
    with engine.begin() as conn:
        keys = conn.execute(text("SELECT board_key FROM boards")).scalars().all()
    assert len(keys) == 3 and len(set(keys)) == 3 and all(len(key) >= 20 for key in keys)
    # 再跑一次什么都不做:已有的 key 不变。
    _migrate_boards_get_a_board_key()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT board_key FROM boards")).scalars().all() == keys


def test_老工作流补上空的_community_slug() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    client.post("/api/workflows", json={"workspace_id": ws, "name": "老的", "description": ""})
    _drop_column("workflows", "community_slug")
    _migrate_workflows_remember_community_slug()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT community_slug FROM workflows")).scalars().all() == [""]
    _migrate_workflows_remember_community_slug()
    assert "community_slug" in _columns("workflows")


def test_老资产补上空的_community() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    client.post("/api/entities", json={"workspace_id": ws, "kind": "prop", "name": "红伞"})
    _drop_column("entities", "community")
    _migrate_entities_remember_community()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT community FROM entities")).scalars().all() == ["{}"]
    _migrate_entities_remember_community()
    assert "community" in _columns("entities")
    listed = client.get("/api/entities", params={"workspace_id": ws})
    assert listed.status_code == 200 and len(listed.json()) == 1
