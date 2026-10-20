"""迁移脚本本身:新库一路建到 head;从 0001 升上来的库一行业不丢。

表结构不再由 `create_all` 猜 —— `cloud.app.create_app()` 启动时执行的就是这两条迁移。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_migrations_build_the_full_schema(tmp_path):
    from cloud.schema import upgrade_database

    path = tmp_path / "fresh.db"
    upgrade_database(_url(path))

    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {
            "cloud_users",
            "cloud_sessions",
            "cloud_email_codes",
            "cloud_device_codes",
            "cloud_identities",
            "cloud_oauth_states",
            "cloud_devices",
            "cloud_shares",
            "cloud_share_likes",
            "cloud_share_favorites",
            "cloud_share_comments",
        } <= tables

        columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_users)")}
        assert {"display_name", "handle", "avatar_seed"} <= columns

        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == ("0002",)

        unique_handle = [
            row[1]
            for row in connection.execute("PRAGMA index_list('cloud_users')")
            if row[1] == "ix_cloud_users_handle" and row[2] == 1
        ]
        assert unique_handle == ["ix_cloud_users_handle"]


def test_upgrading_a_0001_database_keeps_rows_and_leaves_identity_empty(tmp_path):
    """已有账号**不猜一个昵称**给它们:迁移只加列,身份保持空;写接口会要求用户自己起名。"""
    from cloud.schema import upgrade_database

    path = tmp_path / "existing.db"
    url = _url(path)
    upgrade_database(url, "0001")

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cloud_users (id, email, password_hash, email_verified_at, created_at) "
            "VALUES ('u1', 'old@example.com', NULL, NULL, '2026-01-01 00:00:00.000000')"
        )
        connection.commit()

    upgrade_database(url, "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT email, display_name, handle, avatar_seed FROM cloud_users WHERE id = 'u1'"
        ).fetchone() == ("old@example.com", None, None, None)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"cloud_shares", "cloud_share_likes", "cloud_share_favorites", "cloud_share_comments"} <= tables
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0002",)
