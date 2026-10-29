"""`cloud_login` 从存会话 cookie 改为存设备令牌的那条迁移(ADR 0088 第 1 步)。

旧行里只有一枚 cookie,离线换不出令牌:迁移删掉旧形状的表,由 create_all 按新形状建回(已登录的人重新登录一次)。
既验旧形状真的被换掉、新形状能用,也验再跑一次什么都不做(不会把新形状里刚登录的那一行删掉)。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _create_current_schema, _migrate_cloud_login_keeps_a_device_token
from tests.util import fresh_client


def _columns() -> set[str]:
    with engine.begin() as conn:
        return {row[1] for row in conn.execute(text("PRAGMA table_info(cloud_login)"))}


def test_the_cookie_shaped_table_is_rebuilt_and_rerun_is_a_noop() -> None:
    fresh_client()
    with engine.begin() as conn:
        user_id = conn.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()
    #: 升级前的形状:一枚会话 cookie(加密列)和它的过期时间,还有一行已登录的数据。
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE cloud_login"))
        conn.execute(text(
            "CREATE TABLE cloud_login (user_id VARCHAR(64) PRIMARY KEY, email VARCHAR(320) NOT NULL, "
            "cookie_name VARCHAR(64) NOT NULL, cookie_value TEXT NOT NULL, expires_at DATETIME NOT NULL, "
            "created_at DATETIME NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO cloud_login VALUES (:user, 'alice@example.com', 'mosael_cloud_session', 'enc', "
            "'2026-11-28 00:00:00', '2026-10-29 00:00:00')"
        ), {"user": user_id})

    _migrate_cloud_login_keeps_a_device_token()
    _create_current_schema()

    assert {"device_token", "device_token_id"} <= _columns()
    assert not ({"cookie_name", "cookie_value", "expires_at"} & _columns())
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM cloud_login")).scalar() == 0
        #: 新形状下登录过的一行:再跑一次迁移不能把它删掉。
        conn.execute(text(
            "INSERT INTO cloud_login (user_id, email, device_token_id, device_token, created_at) "
            "VALUES (:user, 'alice@example.com', 'dt-1', 'enc', '2026-10-29 00:00:00')"
        ), {"user": user_id})

    _migrate_cloud_login_keeps_a_device_token()

    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM cloud_login")).scalar() == 1
