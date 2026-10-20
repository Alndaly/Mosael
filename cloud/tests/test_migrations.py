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
            "cloud_share_notifications",
        } <= tables

        columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_users)")}
        assert {"display_name", "handle", "avatar_seed"} <= columns

        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == ("0003",)

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
        assert {"cloud_share_notifications"} <= tables
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)


def test_notification_table_shape_and_indexes(tmp_path):
    """0003:事件表、两条查询索引、一条"每个槽位最多一条未读"的部分唯一索引;

    **不写任何旧数据回填分支** —— 新表从零张行开始。
    """
    from cloud.schema import upgrade_database

    path = tmp_path / "notifications.db"
    upgrade_database(_url(path))

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]: {"notnull": row[3], "pk": row[5]}
            for row in connection.execute("PRAGMA table_info(cloud_share_notifications)")
        }
        assert set(columns) == {
            "id",
            "recipient_id",
            "actor_id",
            "share_id",
            "kind",
            "comment_id",
            "read_at",
            "created_at",
        }
        assert columns["recipient_id"]["notnull"] == 1
        assert columns["actor_id"]["notnull"] == 1
        assert columns["share_id"]["notnull"] == 1
        assert columns["kind"]["notnull"] == 1
        assert columns["comment_id"]["notnull"] == 0
        assert columns["read_at"]["notnull"] == 0
        assert columns["created_at"]["notnull"] == 1
        assert connection.execute("SELECT COUNT(*) FROM cloud_share_notifications").fetchone() == (0,)

        indexes = {
            row[1]: {"unique": row[2], "partial": row[4]}
            for row in connection.execute("PRAGMA index_list('cloud_share_notifications')")
        }
        assert "idx_cloud_share_notifications_recipient_created" in indexes
        assert "idx_cloud_share_notifications_recipient_read" in indexes
        assert indexes["uq_cloud_share_notifications_unread"]["unique"] == 1
        assert indexes["uq_cloud_share_notifications_unread"]["partial"] == 1

        ordering_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND name = 'idx_cloud_share_notifications_recipient_created'"
        ).fetchone()[0]
        # 新序在前:复合索引的第二列显式降序。
        assert "created_at DESC" in ordering_sql

        unread_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_cloud_share_notifications_unread'"
        ).fetchone()[0]
        assert "WHERE read_at IS NULL" in unread_sql
