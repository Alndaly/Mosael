"""`migrate-plugin-authorization-rejected`:老库的 plugin_instances 补上「上一次被对方拒了令牌」那一列。

`create_all` 不给已有的表加列,所以这一步要真的在一张**没有这一列**的老表上跑 —— 补上、老连接原样不动
并且一律算「没被拒过」(那正是它们的真实状态:此前根本没人记);再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_plugin_authorization_rejected
from app.db.models import PluginInstance, PluginPackage
from tests.util import fresh_client


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("plugin_instances")}


def test_老库补上这一列_老连接算没被拒过_再跑一次什么都不做() -> None:
    fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id="pkg", name="老插件", version="0.1.0", manifest={}))
        db.flush()
        db.add(PluginInstance(id="i1", package_id="pkg", name="老连接", enabled=True, owner_user_id="u"))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE plugin_instances DROP COLUMN authorization_rejected_at"))
    engine.dispose()
    assert "authorization_rejected_at" not in _columns()

    _migrate_plugin_authorization_rejected()
    engine.dispose()

    assert "authorization_rejected_at" in _columns()
    with engine.begin() as conn:
        row = conn.execute(text("SELECT name, authorization_rejected_at FROM plugin_instances WHERE id = 'i1'")).one()
    assert tuple(row) == ("老连接", None)

    _migrate_plugin_authorization_rejected()
    engine.dispose()
    assert "authorization_rejected_at" in _columns()
