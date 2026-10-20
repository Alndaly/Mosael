"""Cloud 自己的数据库底座。

表结构**只由 `migrations/` 里的 Alembic 脚本演进**,启动时升到 head —— 没有"模型也能建表"的
`create_all` 平行路径,也就没有"新库和迁移出来的库长得不一样"这种事。
"""

from __future__ import annotations

from sqlalchemy import JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

#: JSON 列:PostgreSQL 上落 JSONB,SQLite 上用 JSON(两种库存的是同一份结构)。
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.is_sqlite = url.startswith("sqlite")
        connect_args = {"check_same_thread": False} if self.is_sqlite else {}
        self.engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
        if self.is_sqlite:
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def migrate(self) -> None:
        """把库升到最新迁移。表结构不从这里推断,只执行 `migrations/` 里的脚本。"""
        from cloud.schema import upgrade_database

        upgrade_database(self.url)

    def session(self) -> Session:
        return self.sessions()

    def dispose(self) -> None:
        self.engine.dispose()


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    """删号靠外键级联把会话 / 设备一起带走,所以 SQLite 上必须打开 foreign_keys。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()
