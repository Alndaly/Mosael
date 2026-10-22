"""桌面端登录 MosaelCloud 的那张 `cloud_login` 表。

老库里没有这张表(设备绑定那一版存的是 `cloud_bindings`,已经整张删掉),所以升级时得建出来。
这一步走的是自研 `migration_plan` 的 AFTER_SCHEMA:模型在,`create_all` 建新表,迁移再补一道
checkfirst 并记账。判据三条:**表在且列对**、**从没有这张表的库上也建得出来**、**再跑一次是 no-op**。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import engine
from app.db.migrations import _migrate_cloud_login_table, init_db
from app.db.safety import DATABASE_SCHEMA_VERSION
from tests.util import fresh_client

EXPECTED_COLUMNS = {"user_id", "email", "cookie_name", "cookie_value", "expires_at", "created_at"}


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("cloud_login")}


def test_the_schema_version_is_the_one_that_knows_this_migration() -> None:
    #: 这条迁移只关心「版本号已经越过了它引入的那一版」;后续迁移只增不减地往上走,
    #: 所以断言用 >= 而不是钉死某个数字(钉死的话每加一次迁移都要回来改这里)。
    assert DATABASE_SCHEMA_VERSION >= 36


def test_a_fresh_database_has_the_table_with_the_declared_columns() -> None:
    fresh_client()

    assert _columns() == EXPECTED_COLUMNS


def test_an_old_database_without_the_table_gets_it() -> None:
    """`create_all` 只建缺的表;这一步是给老库补的那道 —— 把表删掉再跑,它必须回来。"""
    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE cloud_login"))
    engine.dispose()

    _migrate_cloud_login_table()

    assert _columns() == EXPECTED_COLUMNS


def test_running_the_whole_plan_again_is_a_no_op() -> None:
    """迁移在真实机器上会被重启反复经过 —— 第二次不能炸,也不能把表弄丢。"""
    fresh_client()

    init_db()
    _migrate_cloud_login_table()

    assert _columns() == EXPECTED_COLUMNS
