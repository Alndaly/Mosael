from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_drop_local_publish_accounts
from tests.util import fresh_client


def _insert_legacy_account(conn, *, account_id: str, ws: str, platform: str, profile_id: str) -> None:
    """手写一条「拆分前」的行:folder/webhook 账号 + 它连带产生的空壳浏览器档案。

    直接写 SQL 而不是走 create_account —— 那个函数在这次改动里已经不再接受 folder/webhook 了,
    而迁移要处理的正是**改动之前**留在库里的数据。
    """
    conn.execute(
        text('INSERT INTO browser_profiles (id, workspace_id, name, "partition", enabled, created_at, updated_at) '
             "VALUES (:id, :ws, '空壳', :part, 1, datetime('now'), datetime('now'))"),
        {"id": profile_id, "ws": ws, "part": f"persist:openstudio-{account_id}"},
    )
    conn.execute(
        text(
            "INSERT INTO publish_accounts (id, workspace_id, profile_id, platform, name, config, enabled, "
            "binding_status, created_at) "
            "VALUES (:id, :ws, :pid, :platform, :name, :config, 1, 'unknown', datetime('now'))"
        ),
        {
            "id": account_id,
            "ws": ws,
            "pid": profile_id,
            "platform": platform,
            "name": f"旧{platform}",
            "config": '{"directory": "/tmp/out"}',
        },
    )


def test_cleanup_drops_local_accounts_and_their_shell_profiles() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with engine.begin() as conn:
        _insert_legacy_account(conn, account_id="acc-folder", ws=ws, platform="folder", profile_id="prof-folder")
        _insert_legacy_account(conn, account_id="acc-hook", ws=ws, platform="webhook", profile_id="prof-hook")

    _migrate_drop_local_publish_accounts()

    with engine.begin() as conn:
        # 账号表里不该再有它们
        left = conn.execute(
            text("SELECT COUNT(*) FROM publish_accounts WHERE platform IN ('folder','webhook')")
        ).scalar()
        assert left == 0

        # 空壳档案要一起清掉 —— 它们是 create_account 的副产品,永远不会有登录态
        shells = conn.execute(
            text("SELECT COUNT(*) FROM browser_profiles WHERE id IN ('prof-folder','prof-hook')")
        ).scalar()
        assert shells == 0, "空壳浏览器档案没有被清理"


def test_cleanup_is_idempotent_and_leaves_real_accounts_alone() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with engine.begin() as conn:
        _insert_legacy_account(conn, account_id="acc-folder", ws=ws, platform="folder", profile_id="prof-folder")
        # 一个真平台账号:它的档案是真的登录身份,绝不能被这次迁移碰到
        _insert_legacy_account(conn, account_id="acc-douyin", ws=ws, platform="douyin", profile_id="prof-douyin")

    _migrate_drop_local_publish_accounts()
    _migrate_drop_local_publish_accounts()  # 再跑一次:必须幂等

    with engine.begin() as conn:
        assert conn.execute(
            text("SELECT COUNT(*) FROM publish_accounts WHERE id = 'acc-douyin'")
        ).scalar() == 1
        assert conn.execute(
            text("SELECT COUNT(*) FROM browser_profiles WHERE id = 'prof-douyin'")
        ).scalar() == 1, "真平台账号的登录档案被误删了"
