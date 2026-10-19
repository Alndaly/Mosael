"""Cloud 自己的数据库底座。

新服务、没有历史数据,所以建表用 `Base.metadata.create_all` —— 没有需要逐步演进的旧形状。
一旦线上有了真实数据,表结构变化就该换成显式迁移(和社区服务一样);这里不预先造一套用不到
的迁移框架(那正是"为了以后可能用到加东西")。
"""

from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


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

    def create_all(self) -> None:
        # 先 import 模型,`Base.metadata` 才有表。
        from cloud import models  # noqa: F401

        Base.metadata.create_all(bind=self.engine)

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
