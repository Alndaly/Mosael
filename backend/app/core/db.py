from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
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


def _migrate_kb_schema() -> None:
    """KB 彻底重写(Dify 式 datasets):项目未上线,旧 kb 表直接删表重建。
    幂等:仅当旧结构存在(有 kb_documents 却无 kb_datasets)时 DROP 一次,create_all 随后重建。"""
    tables = set(inspect(engine).get_table_names())
    if "kb_documents" in tables and "kb_datasets" not in tables:
        with engine.begin() as conn:
            # 先删子表 / FTS 虚表,再删父表(FK)
            for table in ("kb_chunks_fts", "kb_chunks", "kb_documents"):
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


def init_db() -> None:
    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    _migrate_kb_schema()
    Base.metadata.create_all(bind=engine)


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
