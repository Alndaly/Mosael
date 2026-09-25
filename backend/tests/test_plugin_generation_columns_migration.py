"""`migrate-plugin-generation-columns`:老库补上插件可以是生成供应商(ADR 0020)要的三列。

`create_all` 不给已有的表加列,所以这一步要真的在一张**没有这几列**的老表上跑 —— 补上、带着
索引,老数据原样不动;再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import engine
from app.db.migrations import _migrate_plugin_generation_columns
from tests.util import fresh_client


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_老库补上三列_老数据不动_再跑一次什么都不做() -> None:
    fresh_client()
    # SQLite 删不掉带外键的列 —— 把 provider_profiles 按老形状重建一张(外键检查先关掉)。
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        conn.exec_driver_sql(
            "CREATE TABLE provider_profiles_old AS SELECT id, owner_user_id, name, vendor, base_url, auth_type,"
            " extra, enabled, created_at, updated_at FROM provider_profiles"
        )
        conn.exec_driver_sql("DROP TABLE provider_profiles")
        conn.exec_driver_sql("ALTER TABLE provider_profiles_old RENAME TO provider_profiles")
        conn.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_models DROP COLUMN declared_capabilities"))
        conn.execute(text("ALTER TABLE plugin_instances DROP COLUMN capability_status"))
        conn.execute(text(
            "INSERT INTO provider_profiles (id, owner_user_id, name, vendor, base_url, auth_type, extra, enabled,"
            " created_at, updated_at) VALUES ('p1', 'u', '老连接', 'openai', '', 'api_key', '{}', 1,"
            " CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
    engine.dispose()
    assert "plugin_instance_id" not in _columns("provider_profiles")

    _migrate_plugin_generation_columns()
    engine.dispose()

    assert "plugin_instance_id" in _columns("provider_profiles")
    assert "declared_capabilities" in _columns("provider_models")
    assert "capability_status" in _columns("plugin_instances")
    assert "ix_provider_profiles_plugin_instance_id" in {
        index["name"] for index in inspect(engine).get_indexes("provider_profiles")
    }
    with engine.begin() as conn:
        row = conn.execute(text("SELECT name, plugin_instance_id FROM provider_profiles WHERE id = 'p1'")).one()
    assert tuple(row) == ("老连接", None), "老连接不是插件连接"

    _migrate_plugin_generation_columns()
    engine.dispose()
    assert "plugin_instance_id" in _columns("provider_profiles")
