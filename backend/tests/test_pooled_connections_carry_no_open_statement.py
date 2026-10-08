"""连接还回池子时不带着没读完的语句 —— 不然下一个借到它的人删表,SQLite 报 SQLITE_LOCKED「database table is locked」。

现场:全量跑时 `fresh_client()` 的 `drop_all` 偶尔红在 `database table is locked`(test_老库里没有发布表_迁移什么都不做,
两次,不同的 worker)。前一条测试 `next(row for row in conn.execute(...) if ...)` 读了一行就丢下了结果:Python 3.11 起
`rollback()` 不再 reset 语句,连接带着那条没结束的 PRAGMA 回了池子;结果对象在引用环里,要等循环垃圾回收才放。垃圾回收
没赶在下一条测试之前跑、池子又恰好把这条连接给了 `drop_all`,就红。关掉垃圾回收(`gc.disable()`)按顺序跑那两条,
次次都红。

修在 `app/core/db`:连接记着自己开出去的游标,还回池子时一个不留地关掉。这里不靠垃圾回收的时机:手里攥着那个没读完的
结果(和它被引用环留住是同一个效果),再保证下一次借到的是同一条连接。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import engine
from tests.util import fresh_client


@pytest.fixture
def three_rows():
    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE leak_probe (n INTEGER)"))
        conn.execute(text("INSERT INTO leak_probe (n) VALUES (1), (2), (3)"))
    #: 池子清空:下面借出、还回的就是同一条连接,不看池子把哪条给谁
    engine.dispose()
    yield
    engine.dispose()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS leak_probe"))


def _drop_on_the_same_connection(first) -> None:
    with engine.begin() as conn:
        assert conn.connection.driver_connection is first, "借到的不是同一条连接,这条测试就没测到什么"
        conn.execute(text("DROP TABLE leak_probe"))


def test_结果没读完就还了连接_下一个借到它的人照样删得了表(three_rows) -> None:
    with engine.connect() as conn:
        first = conn.connection.driver_connection
        unfinished = conn.execute(text("SELECT n FROM leak_probe ORDER BY n"))
        assert unfinished.fetchone() == (1,)  # 读一行就不读了,结果还攥在手里
    _drop_on_the_same_connection(first)
    #: 连接还了,那个结果就不能再读 —— 再读读的是别人手里的连接
    with pytest.raises(SQLAlchemyError):
        unfinished.fetchone()


def test_直接拿驱动连接执行的也一样(three_rows) -> None:
    """迁移里有直接拿 DBAPI 连接写 SQL 的;sqlite3 的 `Connection.execute` 在 C 里开游标,不经过 `cursor()`。"""
    raw = engine.raw_connection()
    first = raw.driver_connection
    unfinished = first.execute("SELECT n FROM leak_probe ORDER BY n")
    assert unfinished.fetchone() == (1,)
    raw.close()
    _drop_on_the_same_connection(first)
