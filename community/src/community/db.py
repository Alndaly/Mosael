"""数据库:引擎、会话、两种可移植的列类型。

生产跑 PostgreSQL,本地和测试跑 SQLite —— 所以这里只用两边都有的东西:时间一律按 UTC 存、读出来带时区
(SQLite 不存时区,读出来的是「天真」时间,这里补上);JSON 在 Postgres 上落 JSONB。表结构的变化一律
走 Alembic 迁移(migrations/),不在读取代码里认两种形状(ADR 0006)。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

#: 约束的命名规则。Postgres 上 Alembic 删改约束要按名字找,名字得是确定的。
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class UTCDateTime(TypeDecorator[datetime]):
    """存 UTC、读出来带时区。进来的「天真」时间按 UTC 理解。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


#: JSON 列:Postgres 上是 JSONB。
JSONType = JSON().with_variant(JSONB(), "postgresql")


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:  # pragma: no cover - 连接钩子
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    # 按天聚合用的是数据库里的 date():会话时区钉成 UTC,和 SQLite 那边(存的就是 UTC)切出同样的天。
    return create_engine(
        url, pool_pre_ping=True, pool_size=10, max_overflow=10, connect_args={"options": "-c timezone=UTC"}
    )


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


__all__ = ["Base", "JSONType", "UTCDateTime", "make_engine", "make_sessionmaker", "new_id", "session_scope", "utcnow"]
