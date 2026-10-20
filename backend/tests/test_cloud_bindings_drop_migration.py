"""本地 `cloud_bindings` 表被删掉的那一次迁移。

云端设备绑定机制已经移除:Cloud 那侧的表、路由和模型一起删了,本地这张只记「谁绑了哪个云端
账号、设备的 token 是什么」的表再没有任何读者。老库里它还在,所以升级时整表 DROP。

判据三条:老形状的库升级后表真的没了、**表里的行没有别处要读**(删就是删,不做搬运),
以及**跑第二次不炸**(迁移在真实机器上会被重启反复经过)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import engine
from app.db.migrations import _migrate_drop_cloud_bindings_table
from tests.util import fresh_client


def _old_shaped_table() -> None:
    """把 `cloud_bindings` 退回迁移前的形状,并塞一行。

    **DDL 之后必须 dispose 连接池**:SQLite 每条连接各自缓存表结构,而迁移里的
    `inspect(engine)` 可能拿到另一条还记着旧样子的连接(见 test_scene_models_move_to_disk_migration)。
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS cloud_bindings"))
        conn.execute(text(
            "CREATE TABLE cloud_bindings ("
            "user_id VARCHAR(64) NOT NULL PRIMARY KEY, "
            "cloud_user_id VARCHAR(64) NOT NULL, "
            "email VARCHAR(320) NOT NULL, "
            "device_id VARCHAR(64) NOT NULL, "
            "token TEXT NOT NULL, "
            "created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO cloud_bindings "
            "(user_id, cloud_user_id, email, device_id, token, created_at) "
            "VALUES ('u-1', 'c-1', 'old@example.com', 'd-1', 'encrypted-token', '2026-01-01 00:00:00')"
        ))
    engine.dispose()


def _tables() -> set[str]:
    return set(inspect(engine).get_table_names())


def test_the_old_bindings_table_is_dropped() -> None:
    fresh_client()
    _old_shaped_table()
    assert "cloud_bindings" in _tables()

    _migrate_drop_cloud_bindings_table()

    assert "cloud_bindings" not in _tables()


def test_running_it_twice_is_a_no_op() -> None:
    fresh_client()
    _old_shaped_table()

    _migrate_drop_cloud_bindings_table()
    _migrate_drop_cloud_bindings_table()

    assert "cloud_bindings" not in _tables()
