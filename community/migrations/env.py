"""Alembic 的运行入口。数据库地址取调用方在 Config 里给的 sqlalchemy.url,没给就取 COMMUNITY_DATABASE_URL。"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from community import models  # noqa: F401 - 注册全部表到 Base.metadata
from community.config import load_settings
from community.db import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    return config.get_main_option("sqlalchemy.url") or load_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # SQLite 改表要走「建新表、拷数据、换名」:render_as_batch 让以后的 alter 在两种库上都能跑。
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
