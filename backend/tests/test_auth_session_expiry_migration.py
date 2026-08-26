"""老库补上 `expires_at` / `kind` 的那一次迁移。

这类迁移只在"老装机第一次跑新版本"时发生一次,肉眼几乎不可能复验,而它错了就是所有人被登出
(或者相反:老行永远不过期,等于这次修复白做)。所以在这里把行为钉死。

判据三条:老行拿到一个**未来**的过期时间(升级不踢人)、`kind` 落成 login(分不出哪些是泄漏的
服务令牌,一律按登录处理)、跑第二次不再改动任何东西。

读取代码里没有"没有过期时间"这个形状 —— 迁移跑完就不存在了(docs/adr/0006)。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.config import LOGIN_SESSION_TTL
from app.core.tokens import token_digest
from app.core.db import engine
from app.db.migrations import _migrate_auth_session_expiry
from tests.util import fresh_client


def _old_shaped_table() -> None:
    """把 auth_sessions 退回迁移前的形状(只有 token / user_id / created_at)。

    **DDL 之后必须清掉连接池**:SQLite 的每条连接各自缓存表结构,而 `engine.begin()` 每次
    从池里拿一条。这里 DROP+CREATE 用的是一条,迁移里 `inspect(engine)` 用的可能是另一条 ——
    那一条还记着 DROP 之前的样子,于是迁移以为 `kind` 不存在、再 ADD 一次,SQLite 回
    `duplicate column name`。

    macOS 上撞不到(池里往往就一条连接被反复复用),Linux 的 CI 上必现 —— 这是本地绿、
    CI 红的全部原因。
    """
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS auth_sessions"))
        conn.execute(
            text(
                "CREATE TABLE auth_sessions ("
                "token VARCHAR(80) NOT NULL PRIMARY KEY, "
                "user_id VARCHAR(64) NOT NULL, "
                "created_at DATETIME NOT NULL)"
            )
        )
    engine.dispose()


def _insert_legacy(token: str, *, age_days: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO auth_sessions (token,user_id,created_at) VALUES (:t,'u-1',:c)"),
            {"t": token, "c": (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=age_days)).isoformat(sep=" ")},
        )


def _rows() -> dict[str, tuple[str, str]]:
    with engine.begin() as conn:
        return {
            row[0]: (row[1], row[2])
            for row in conn.execute(text("SELECT token, kind, expires_at FROM auth_sessions")).fetchall()
        }


def test_legacy_rows_get_a_future_expiry_and_stay_logged_in() -> None:
    fresh_client()  # 建库
    _old_shaped_table()
    _insert_legacy("tok-yesterday", age_days=1)
    _insert_legacy("tok-ancient", age_days=400)

    _migrate_auth_session_expiry()

    rows = _rows()
    horizon = datetime.now(UTC).replace(tzinfo=None) + LOGIN_SESSION_TTL
    for token in ("tok-yesterday", "tok-ancient"):
        kind, expires_at = rows[token]
        assert kind == "login", f"{token} 的 kind 没有回填"
        moment = datetime.fromisoformat(expires_at)
        assert moment > datetime.now(UTC).replace(tzinfo=None), f"{token} 一升级就过期了 —— 用户会被登出"
        # 老行分不出登录还是泄漏的服务令牌,所以给一个完整周期,不多给。
        assert moment <= horizon + timedelta(minutes=1)


def test_running_it_twice_changes_nothing() -> None:
    fresh_client()
    _old_shaped_table()
    _insert_legacy("tok-idempotent", age_days=3)

    _migrate_auth_session_expiry()
    first = _rows()
    _migrate_auth_session_expiry()

    assert _rows() == first, "迁移不幂等 —— 第二次启动会把过期时间又往后推一个周期"


def test_it_is_a_no_op_once_the_columns_exist() -> None:
    """新装机上 create_all 已经把两列建好,迁移不该碰任何行。"""
    client = fresh_client()
    live = client.headers["Authorization"].removeprefix("Bearer ")
    before = _rows()

    _migrate_auth_session_expiry()

    assert _rows() == before
    assert token_digest(live) in before  # 库里存的是哈希
