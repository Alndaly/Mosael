"""Alembic 的运行入口。

数据库地址优先取调用方放在 Config 里的 `sqlalchemy.url`(测试与 `cloud.cli` 都这样传);
没给就取 `CloudConfig.from_env()` 解析出的地址,和 uvicorn 启动时那一份是同一个来源。
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from cloud import models  # noqa: F401 - 把全部表注册到 Base.metadata
from cloud.config import CloudConfig
from cloud.db import Base

config = context.config
target_metadata = Base.metadata


def database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    resolved = CloudConfig.from_env()
    if not resolved.database_url:
        # SQLite 不会替我们建目录;直接 `alembic upgrade` 时也要能跑。
        resolved.data_dir.mkdir(parents=True, exist_ok=True)
    return resolved.resolved_database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        # SQLite 改表要走「建新表、拷数据、换名」;render_as_batch 让同一条迁移在 SQLite 与
        # PostgreSQL 上都能跑。表结构变化只写在这里,读取代码里不认两种形状。
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
