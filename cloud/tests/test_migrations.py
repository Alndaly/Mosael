"""迁移脚本本身:新库一路建到 head;从 0001 升上来的库一行业不丢。

表结构不再由 `create_all` 猜 —— `cloud.app.create_app()` 启动时执行的就是这两条迁移。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


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
            "cloud_identities",
            "cloud_oauth_states",
            "cloud_shares",
            "cloud_share_likes",
            "cloud_share_favorites",
            "cloud_share_comments",
            "cloud_share_notifications",
        } <= tables

        # 0004 拆掉了设备绑定:两张表在 head 的库里不存在。
        assert not ({"cloud_device_codes", "cloud_devices"} & tables)

        columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_users)")}
        assert {"display_name", "handle", "avatar_seed"} <= columns

        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == ("0006",)

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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0006",)


def test_0004_drops_the_device_binding_tables(tmp_path):
    """升到 0003 时两张表还在(0001 建的);0004 把它们连同数据一起删掉。"""
    from cloud.schema import upgrade_database

    path = tmp_path / "binding.db"
    url = _url(path)
    upgrade_database(url, "0003")

    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"cloud_device_codes", "cloud_devices"} <= tables
        connection.execute(
            "INSERT INTO cloud_users (id, email, password_hash, email_verified_at, created_at) "
            "VALUES ('u1', 'old@example.com', NULL, NULL, '2026-01-01 00:00:00.000000')"
        )
        connection.execute(
            "INSERT INTO cloud_devices (id, user_id, name, token_hash, created_at) "
            "VALUES ('d1', 'u1', 'Mac', 'hash', '2026-01-01 00:00:00.000000')"
        )
        connection.commit()

    upgrade_database(url, "head")

    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not ({"cloud_device_codes", "cloud_devices"} & tables)
        # 账号本身不受影响。
        assert connection.execute("SELECT email FROM cloud_users WHERE id = 'u1'").fetchone() == ("old@example.com",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0006",)


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


def _share_insert(kind: str):
    return (
        "INSERT INTO cloud_shares (id, owner_user_id, kind, title, payload, bytes, license, status, "
        "downloads, created_at, updated_at) VALUES (?, 'u1', ?, 'Title', '{}', 2, NULL, 'listed', 0, "
        "'2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')"
    )


def test_0005_allows_plugin_kind_and_0006_adds_official_and_seed_slug(tmp_path):
    """① 0005 把 CHECK 换成含 plugin 的;②③ 0006 加 `official` 与种子去重用的 `slug`。

    先钉住 0004 的旧语义(plugin 被 CHECK 拒绝),再升到 head 看它被放开、非法值仍被拒。
    """
    from cloud.schema import upgrade_database

    path = tmp_path / "plugin.db"
    url = _url(path)
    upgrade_database(url, "0004")

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cloud_users (id, email, created_at) "
            "VALUES ('u1', 'old@example.com', '2026-01-01 00:00:00.000000')"
        )
        # 0004:CHECK 只认 workflow / board。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(_share_insert("plugin"), ("s1", "plugin"))
        connection.commit()

    upgrade_database(url, "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0006",)

        # ① plugin 现在能建;非法值仍然被数据库兜住。
        connection.execute(_share_insert("plugin"), ("s1", "plugin"))
        connection.execute(_share_insert("workflow"), ("s2", "workflow"))
        connection.commit()
        assert connection.execute("SELECT kind FROM cloud_shares WHERE id = 's1'").fetchone() == ("plugin",)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(_share_insert("theme"), ("s3", "theme"))
        connection.rollback()

        # ② official 非空、默认 false;已有账号升级后就是 false。
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(cloud_users)")}
        assert columns["official"][3] == 1
        assert columns["official"][4] in (0, "0", "false")
        connection.execute(
            "INSERT INTO cloud_users (id, email, created_at) "
            "VALUES ('u2', 'new@example.com', '2026-01-01 00:00:00.000000')"
        )
        connection.commit()
        assert connection.execute("SELECT official FROM cloud_users WHERE id = 'u2'").fetchone() == (0,)
        assert connection.execute("SELECT official FROM cloud_users WHERE id = 'u1'").fetchone() == (0,)

        # ③ slug 可空(用户分享没有它),但同一作者 + 同一 kind + 同一 slug 只能有一行。
        share_columns = {row[1]: row for row in connection.execute("PRAGMA table_info(cloud_shares)")}
        assert share_columns["slug"][3] == 0
        # 多条 NULL 不冲突(用户分享都没有 slug)。
        connection.execute(_share_insert("plugin"), ("s4", "plugin"))
        connection.commit()
        connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's1'")
        connection.commit()
        # kind 进唯一键:另一个 kind 用同一 slug 是允许的。
        connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's2'")
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's4'")
        connection.rollback()


def test_downgrade_from_head_restores_the_0004_shape(tmp_path):
    """⑤ down 能回:head → 0004 之后 plugin 重新被 CHECK 拒绝,official / slug 两列消失。"""
    from cloud.schema import downgrade_database, upgrade_database

    path = tmp_path / "downgrade.db"
    url = _url(path)
    upgrade_database(url)
    downgrade_database(url, "0004")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0004",)
        user_columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_users)")}
        assert "official" not in user_columns
        share_columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_shares)")}
        assert "slug" not in share_columns

        connection.execute(
            "INSERT INTO cloud_users (id, email, created_at) "
            "VALUES ('u1', 'old@example.com', '2026-01-01 00:00:00.000000')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(_share_insert("plugin"), ("s1", "plugin"))
        connection.commit()
        connection.execute(_share_insert("workflow"), ("s2", "workflow"))
        connection.commit()
        assert connection.execute("SELECT COUNT(*) FROM cloud_shares").fetchone() == (1,)
