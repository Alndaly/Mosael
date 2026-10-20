"""表结构迁移的唯一入口。

Cloud 的表结构**只由 `migrations/` 里的脚本演进**。运行时不猜两种形状、不为旧数据写回退分支:
新库直接升到 head,已有库先 `stamp` 到它当前的基线再升级(见 README 的升级步骤)。
"""

from __future__ import annotations

from pathlib import Path

#: src/cloud/schema.py → cloud/migrations
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _config(database_url: str):
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser 把 % 当插值;数据库地址里可能有 %。
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    from alembic import command

    command.upgrade(_config(database_url), revision)


def stamp_database(database_url: str, revision: str) -> None:
    """把一条已经由 `create_all` 建好表的库标到某个版本上(只在升级既有部署时用一次)。"""
    from alembic import command

    command.stamp(_config(database_url), revision)


def downgrade_database(database_url: str, revision: str) -> None:
    """回退到某个版本(运维 / 测试用)。

    **不删用户数据来迁就旧形状**:0005 把 CHECK 换回两个值时,如果库里已经有 `plugin` 行,
    回退会在约束校验处明确失败,由人来决定那些分享怎么处理。
    """
    from alembic import command

    command.downgrade(_config(database_url), revision)
