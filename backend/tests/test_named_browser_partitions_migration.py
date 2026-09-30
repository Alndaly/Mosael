"""具名浏览器会话的登录分区按工作区分开:迁移写下搬家单(谁的旧分区搬到哪),由 Electron 执行器在磁盘上搬。

老库只在第一次升级时经过这一条,肉眼几乎没法复验,所以每条都喂真实的旧形状数据。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_named_browser_partitions_are_per_workspace
from app.db.models import BrowserPartitionMove
from app.domain import browser
from tests.util import fresh_client, worker_client


def _client_and_workspaces(count: int):
    client = fresh_client()
    return client, [client.post("/api/workspaces", json={"name": f"W{i}"}).json()["id"] for i in range(count)]


def _workflow(client, ws: str, graph: dict) -> str:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "流程", "graph": graph}).json()["id"]


def _old_session(ws: str, stored: str, at: str) -> None:
    """旧规则建的具名会话行:名字是清洗后的,分区是 `persist:rpa-<清洗后的名字>`。"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO browser_sessions (id, workspace_id, kind, name, partition, owner_kind, status, last_url, "
                "created_at, updated_at) VALUES (:id, :ws, 'named', :name, :p, 'workflow', 'closed', '', :at, :at)"
            ),
            {"id": f"s-{ws[:6]}-{stored}-{at[-2:]}", "ws": ws, "name": stored, "p": f"persist:rpa-{stored}", "at": at},
        )


def _opener(name: str) -> dict:
    return {"nodes": [{"id": "open", "type": "browser_open", "config": {"session_mode": "named", "session_name": name}}],
            "edges": []}


def _moves() -> list[BrowserPartitionMove]:
    with SessionLocal() as db:
        return list(db.query(BrowserPartitionMove).order_by(BrowserPartitionMove.status, BrowserPartitionMove.session_name))


def test_旧分区归最早用它的工作区_名字从工作流里找回原名() -> None:
    client, (ws_a, ws_b) = _client_and_workspaces(2)
    _workflow(client, ws_a, _opener("xhs-主号"))
    _old_session(ws_b, "xhs", "2026-01-02 00:00:00")
    _old_session(ws_a, "xhs", "2026-01-01 00:00:00")  # A 更早

    _migrate_named_browser_partitions_are_per_workspace()

    moves = _moves()
    pending = [move for move in moves if move.status == "pending"]
    assert len(pending) == 1
    assert pending[0].old_partition == "persist:rpa-xhs"
    # 新分区用的是原名(「xhs-主号」),和领域里此后开会话算出来的是同一个
    assert pending[0].new_partition == browser.named_partition(ws_a, "xhs-主号")
    abandoned = [move for move in moves if move.status == "abandoned"]
    assert [move.workspace_id for move in abandoned] == [ws_b]
    assert ws_a in abandoned[0].reason


def test_清洗后撞名的几个原名_登录归先出现的那个_其余记下来() -> None:
    client, (ws,) = _client_and_workspaces(1)
    _workflow(client, ws, _opener("xhs-主号"))
    _workflow(client, ws, _opener("xhs-副号"))
    _old_session(ws, "xhs", "2026-01-01 00:00:00")

    _migrate_named_browser_partitions_are_per_workspace()

    by_status = {move.status: move for move in _moves()}
    assert by_status["pending"].session_name == "xhs-主号"
    assert by_status["abandoned"].session_name == "xhs-副号"
    assert "xhs-主号" in by_status["abandoned"].reason


def test_找不到原名时用库里的名字_纯ASCII的名字清洗前后本来就一样() -> None:
    _, (ws,) = _client_and_workspaces(1)
    _old_session(ws, "Shop_1", "2026-01-01 00:00:00")

    _migrate_named_browser_partitions_are_per_workspace()

    [move] = _moves()
    assert move.new_partition == browser.named_partition(ws, "Shop_1")
    # Electron 把分区名转小写落盘:旧目录按小写记
    assert move.old_partition == "persist:rpa-shop_1"


def test_重跑不重复写_执行器搬完回报之后不再发() -> None:
    _, (ws,) = _client_and_workspaces(1)
    _old_session(ws, "xhs", "2026-01-01 00:00:00")
    _migrate_named_browser_partitions_are_per_workspace()
    _migrate_named_browser_partitions_are_per_workspace()
    assert len(_moves()) == 1

    worker = worker_client()
    [pending] = worker.get("/api/browser/worker/partition-moves").json()["moves"]
    assert worker.post(f"/api/browser/worker/partition-moves/{pending['id']}", json={"status": "done"}).status_code == 200
    assert worker.get("/api/browser/worker/partition-moves").json()["moves"] == []
    assert worker.post(
        f"/api/browser/worker/partition-moves/{pending['id']}", json={"status": "whatever"}
    ).status_code == 422


def test_新规则建的会话不算旧分区() -> None:
    _, (ws,) = _client_and_workspaces(1)
    with SessionLocal() as db:
        browser.open_session(db, workspace_id=ws, kind="named", name="xhs", actor=None)
    _migrate_named_browser_partitions_are_per_workspace()
    assert _moves() == []
