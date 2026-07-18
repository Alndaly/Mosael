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
    以「kb_documents 是否有 dataset_id 列」判定旧结构 —— 比按表存在判定更稳,
    能修复「kb_datasets 已建但 kb_documents 仍是旧列」的半迁移中间态。create_all 随后重建。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "kb_documents" not in tables:
        return
    columns = {col["name"] for col in inspector.get_columns("kb_documents")}
    if "dataset_id" not in columns:  # 旧结构 → 全量删表重建
        with engine.begin() as conn:
            for table in ("kb_chunks_fts", "kb_chunks", "kb_documents", "kb_datasets"):
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


def _migrate_agent_sessions() -> None:
    """加列迁移(保留对话历史):agent_sessions 增加 provider_profile_id / model。"""
    inspector = inspect(engine)
    if "agent_sessions" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("agent_sessions")}
    with engine.begin() as conn:
        if "provider_profile_id" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN provider_profile_id VARCHAR(64)"))
        if "model" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN model VARCHAR(120)"))
        if "adapter_state" not in columns:
            conn.execute(text("ALTER TABLE agent_sessions ADD COLUMN adapter_state JSON"))


def init_db() -> None:
    from app.db import models  # noqa: F401

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.plugins_dir.mkdir(parents=True, exist_ok=True)
    _migrate_kb_schema()
    _migrate_agent_sessions()
    Base.metadata.create_all(bind=engine)


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
