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
            "cloud_phone_codes",
            "cloud_identities",
            "cloud_oauth_states",
            "cloud_shares",
            "cloud_share_likes",
            "cloud_share_favorites",
            "cloud_share_comments",
            "cloud_share_notifications",
            "cloud_device_tokens",
            "cloud_plans",
            "cloud_subscriptions",
            "cloud_credit_batches",
            "cloud_usage_entries",
            "cloud_gateway_calls",
            "cloud_gateway_models",
            "cloud_model_prices",
            "cloud_upstream_providers",
            "cloud_upstream_channels",
            "cloud_orders",
            "cloud_admin_audit",
        } <= tables

        # 0004 拆掉了设备绑定:两张表在 head 的库里不存在。
        assert not ({"cloud_device_codes", "cloud_devices"} & tables)

        columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_users)")}
        assert {"display_name", "handle", "avatar_seed", "phone", "phone_verified_at", "mfa_enabled_at", "role"} <= columns

        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert version == ("0016",)

        unique_handle = [
            row[1]
            for row in connection.execute("PRAGMA index_list('cloud_users')")
            if row[1] == "ix_cloud_users_handle" and row[2] == 1
        ]
        assert unique_handle == ["ix_cloud_users_handle"]
        unique_phone = [
            row[1]
            for row in connection.execute("PRAGMA index_list('cloud_users')")
            if row[1] == "ix_cloud_users_phone" and row[2] == 1
        ]
        assert unique_phone == ["ix_cloud_users_phone"]


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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016",)


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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016",)


def test_0016_moves_channel_credentials_into_shared_providers(tmp_path):
    """旧通道里的端点 / Key 被抽成供应商;两条同凭据通道复用同一个供应商。"""
    from cloud.schema import upgrade_database

    path = tmp_path / "provider-migration.db"
    url = _url(path)
    upgrade_database(url, "0015")

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cloud_gateway_models (id, label, kind, max_output_tokens, enabled, sort_order, created_at) "
            "VALUES ('m1', 'M1', 'chat', 100, 1, 0, '2026-01-01 00:00:00.000000')"
        )
        connection.execute(
            "INSERT INTO cloud_upstream_channels "
            "(id, model_id, protocol, base_url, upstream_model, api_key_encrypted, priority, enabled, "
            "cooldown_until, note, created_at) VALUES "
            "('c1', 'm1', 'openai', 'https://upstream.example/v1', 'upstream-a', 'sealed', 0, 1, NULL, '', "
            "'2026-01-01 00:00:00.000000')"
        )
        connection.execute(
            "INSERT INTO cloud_upstream_channels "
            "(id, model_id, protocol, base_url, upstream_model, api_key_encrypted, priority, enabled, "
            "cooldown_until, note, created_at) VALUES "
            "('c2', 'm1', 'openai', 'https://upstream.example/v1', 'upstream-b', 'sealed', 1, 1, NULL, '', "
            "'2026-01-02 00:00:00.000000')"
        )
        connection.commit()

    upgrade_database(url, "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM cloud_upstream_providers").fetchone() == (1,)
        assert connection.execute(
            "SELECT c.upstream_model, p.base_url, p.api_key_encrypted "
            "FROM cloud_upstream_channels c JOIN cloud_upstream_providers p ON p.id = c.provider_id "
            "ORDER BY c.priority"
        ).fetchall() == [
            ("upstream-a", "https://upstream.example/v1", "sealed"),
            ("upstream-b", "https://upstream.example/v1", "sealed"),
        ]
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016",)


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
        # **普通复合索引,不带 DESC**(0008 归一)。B-tree 能反向扫,排序方向不改变"按
        # recipient_id 取、按 created_at 排"这件事;而 DESC 是表达式,会让真 Postgres 上
        # 模型声明与库结构永久对不上(alembic check 先 remove 再 add)。SQLite 的反射不保留
        # 方向,所以这个漂移只在 PG 上暴露 —— 归一之后两个库都对得上。
        assert "created_at DESC" not in ordering_sql
        assert "recipient_id, created_at" in ordering_sql

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
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016",)

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

        # ③ slug 可空(用户分享没有它),但同一作者 + 同一 kind + 同一 slug + 同一 locale
        #    只能有一行。
        share_columns = {row[1]: row for row in connection.execute("PRAGMA table_info(cloud_shares)")}
        assert share_columns["slug"][3] == 0
        # 多条 NULL 不冲突(用户分享都没有 slug)。
        connection.execute(_share_insert("plugin"), ("s4", "plugin"))
        connection.commit()
        # 0007 之前插入的行由迁移 / 数据库默认补成 zh-CN —— 既有行没有语言信息可推断,
        # 只能按"迁移当时的内容都是中文"来定。
        assert connection.execute("SELECT locale FROM cloud_shares WHERE id = 's4'").fetchone() == ("zh-CN",)
        connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's1'")
        connection.commit()
        # kind 进唯一键:另一个 kind 用同一 slug 是允许的。
        connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's2'")
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's4'")
        connection.rollback()
        # ① locale 也进唯一键:同一 slug 的两种语言可以共存,同语言仍然只许一行。
        connection.execute(
            "UPDATE cloud_shares SET slug = 'mosael.official.example', locale = 'en-US' WHERE id = 's4'"
        )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM cloud_shares WHERE slug = 'mosael.official.example'"
        ).fetchone() == (3,)


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
        assert "locale" not in share_columns

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


def _share_insert_with_locale(locale: str):
    return (
        "INSERT INTO cloud_shares (id, owner_user_id, kind, title, payload, bytes, license, status, "
        "downloads, locale, created_at, updated_at) VALUES (?, 'u1', 'plugin', 'Title', '{}', 2, NULL, "
        "'listed', 0, ?, '2026-01-01 00:00:00.000000', '2026-01-01 00:00:00.000000')"
    )


def test_0007_backfills_existing_rows_with_zh_cn_and_checks_two_locales(tmp_path):
    """① 0007:`locale` NOT NULL、既有行填 `zh-CN`、只许两种值,唯一键扩到四列。"""
    from cloud.schema import upgrade_database

    path = tmp_path / "locale.db"
    url = _url(path)
    upgrade_database(url, "0006")

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cloud_users (id, email, created_at) "
            "VALUES ('u1', 'old@example.com', '2026-01-01 00:00:00.000000')"
        )
        # 0006 的形状里没有 locale 列。
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("SELECT locale FROM cloud_shares")
        connection.rollback()
        connection.execute(_share_insert("plugin"), ("s1", "plugin"))
        connection.commit()

    upgrade_database(url, "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016",)
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(cloud_shares)")}
        assert columns["locale"][3] == 1  # NOT NULL
        # 既有行没有语言信息可推断 —— 迁移只能把它们都当中文,并在迁移里写明。
        assert connection.execute("SELECT locale FROM cloud_shares WHERE id = 's1'").fetchone() == ("zh-CN",)

        # 新行不显式给 locale 时,数据库默认也是 zh-CN。
        connection.execute(_share_insert("workflow"), ("s2", "workflow"))
        connection.commit()
        assert connection.execute("SELECT locale FROM cloud_shares WHERE id = 's2'").fetchone() == ("zh-CN",)

        # 只有 zh-CN / en-US 两种值,第三个值被数据库拒绝。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(_share_insert_with_locale("fr-FR"), ("s3", "fr-FR"))
        connection.rollback()

        # 唯一索引是 (owner, kind, slug, locale):同 slug 的两种语言能共存,
        # 同一种语言重复仍然被拒。
        connection.execute(
            "UPDATE cloud_shares SET slug = 'mosael.official.example', locale = 'zh-CN' WHERE id = 's1'"
        )
        connection.commit()
        connection.execute(_share_insert_with_locale("en-US"), ("s4", "en-US"))
        connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's4'")
        connection.execute(_share_insert_with_locale("zh-CN"), ("s5", "zh-CN"))
        connection.commit()
        # 同一种语言再来一行同 slug → 撞四列唯一索引。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's5'"
            )
        connection.rollback()

        index_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_cloud_shares_owner_kind_slug_locale'"
        ).fetchone()[0]
        assert "UNIQUE" in index_sql.upper()
        assert all(column in index_sql for column in ("owner_user_id", "kind", "slug", "locale"))
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_cloud_shares_owner_kind_slug'"
        ).fetchone() == (0,)


def test_0007_downgrade_round_trip_restores_the_0006_shape(tmp_path):
    """⑤ 0007 建得出、down 得回;再升回来也还是同一份数据(行不丢)。"""
    from cloud.schema import downgrade_database, upgrade_database

    path = tmp_path / "locale-downgrade.db"
    url = _url(path)
    upgrade_database(url)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cloud_users (id, email, created_at) "
            "VALUES ('u1', 'old@example.com', '2026-01-01 00:00:00.000000')"
        )
        connection.execute(_share_insert("plugin"), ("s1", "plugin"))
        connection.execute("UPDATE cloud_shares SET slug = 'mosael.official.example' WHERE id = 's1'")
        connection.commit()

    downgrade_database(url, "0006")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0006",)
        share_columns = {row[1] for row in connection.execute("PRAGMA table_info(cloud_shares)")}
        assert "locale" not in share_columns
        assert connection.execute("SELECT id, slug FROM cloud_shares").fetchall() == [
            ("s1", "mosael.official.example")
        ]
        indexes = {row[1] for row in connection.execute("PRAGMA index_list('cloud_shares')")}
        assert "uq_cloud_shares_owner_kind_slug" in indexes
        assert "uq_cloud_shares_owner_kind_slug_locale" not in indexes

    upgrade_database(url, "head")

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0016",)
        assert connection.execute("SELECT id, locale FROM cloud_shares").fetchall() == [("s1", "zh-CN")]


def test_models_and_migrations_do_not_drift(tmp_path):
    """⑤ `alembic check` 零漂移:models.py 与 migrations/ 讲的是同一份表结构。"""
    from alembic import command

    from cloud.schema import _config, upgrade_database

    path = tmp_path / "drift.db"
    url = _url(path)
    upgrade_database(url)
    command.check(_config(url))
