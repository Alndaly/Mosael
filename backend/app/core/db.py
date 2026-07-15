from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_db() -> None:
    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
