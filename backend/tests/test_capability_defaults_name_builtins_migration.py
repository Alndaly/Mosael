"""`plugin_capability_defaults` 能存内置实现的那一次迁移(`_migrate_capability_defaults_name_builtins`)。

降噪有三个本机引擎,在「设置 → 能力提供方」点名 RNNoise 此前报「没有这个连接」(用户截图):那张表只有一列指向插件连接的
`instance_id`。判据:老行(都是插件连接)原样搬过去;迁移后能存内置实现;两列都空的行存不进去;跑第二次不动。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_capability_defaults_name_builtins
from tests.util import fresh_client


def _connection() -> str:
    from app.db.models import PluginInstance, PluginPackage

    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.test.parser", name="解析", version="1", manifest={"id": "dev.test.parser"}))
        db.flush()
        instance = PluginInstance(owner_user_id="u1", package_id="dev.test.parser", name="云端", enabled=True, config={})
        db.add(instance)
        db.commit()
        return instance.id


def _old_shaped_table(instance_id: str) -> None:
    """退回迁移前的形状:一行指向还在的连接,一行指向早删了的。DDL 之后清掉连接池 —— 各条连接各自缓存表结构
    (见 test_auth_session_expiry_migration)。"""
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("DROP TABLE IF EXISTS plugin_capability_defaults"))
        conn.execute(text(
            "CREATE TABLE plugin_capability_defaults ("
            "owner_user_id VARCHAR(64) NOT NULL, capability VARCHAR(40) NOT NULL, "
            "instance_id VARCHAR(64) NOT NULL REFERENCES plugin_instances (id) ON DELETE CASCADE, "
            "updated_at DATETIME NOT NULL, PRIMARY KEY (owner_user_id, capability))"
        ))
        conn.execute(text(
            "INSERT INTO plugin_capability_defaults VALUES ('u1', 'document_parse', :instance, :at), "
            "('u1', 'public_url', 'gone', :at)"
        ), {"instance": instance_id, "at": datetime.now(UTC)})
        conn.execute(text("PRAGMA foreign_keys = ON"))
    engine.dispose()


def _rows() -> list[tuple]:
    with engine.begin() as conn:
        return list(conn.execute(text(
            "SELECT owner_user_id, capability, instance_id, builtin_id FROM plugin_capability_defaults ORDER BY capability"
        )))


def test_老行原样搬过去_之后能存内置实现_跑第二次不动() -> None:
    fresh_client()
    instance = _connection()
    _old_shaped_table(instance)

    _migrate_capability_defaults_name_builtins()
    engine.dispose()
    assert "builtin_id" in {c["name"] for c in inspect(engine).get_columns("plugin_capability_defaults")}
    assert _rows() == [("u1", "document_parse", instance, None)], "悬空的那行不搬"

    from app.domain.plugins import capability_defaults

    with SessionLocal() as db:
        capability_defaults.set_default(db, "u1", "audio_denoise", "builtin:rnnoise",
                                        builtin_ids=frozenset({"builtin:ffmpeg", "builtin:rnnoise"}))
        assert capability_defaults.default_of(db, "u1", "audio_denoise") == "builtin:rnnoise"

    _migrate_capability_defaults_name_builtins()
    assert _rows() == [("u1", "audio_denoise", None, "builtin:rnnoise"), ("u1", "document_parse", instance, None)]


def test_两列都空的行存不进去() -> None:
    fresh_client()
    with engine.begin() as conn, pytest.raises(IntegrityError):
        conn.execute(text(
            "INSERT INTO plugin_capability_defaults (owner_user_id, capability, instance_id, builtin_id, updated_at) "
            "VALUES ('u2', 'audio_denoise', NULL, NULL, :at)"
        ), {"at": datetime.now(UTC)})
