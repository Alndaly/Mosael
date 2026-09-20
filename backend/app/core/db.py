"""数据库的**底座**:引擎、会话、Base。

`app/core` 是最底层 —— 谁都可以 import 它,它不 import 任何人。所以这里**不放迁移**:
迁移要认识每一个领域(声音克隆的 venv 往哪搬、插件表怎么拆),而这个模块被二十几处
import。两个方向相反的职责挤在一起时,迁移只能靠写在函数体里的 `from app.domain import …`
硬撑——那不是技巧,是"层分错了"的自白。迁移住在 `app/db/migrations.py`,它在依赖序的顶端。
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import UTC, datetime

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)



class Base(DeclarativeBase):
    pass


#: 发布账号登录分区的命名前缀(完整分区名 = persist:<PARTITION_PREFIX>-<accountId>)。
#: 与 electron/publish/accountViews.ts 的同名约定必须一致——两边拼的是同一个磁盘目录。
#: 由 contracts/shared-constants.json 钉住(不一致 = 所有发布账号的登录态凭空消失)。
PARTITION_PREFIX = "mosael"


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


def now() -> datetime:
    """朴素 UTC 时间戳。**和 `db/model_base.now` 是同一个语义**(那边是给 ORM 列的默认值)。

    `datetime.utcnow()` 自 Python 3.12 起已废弃(3.15 计划移除),而它是全库时间戳的来源之一,
    所以这里换成等价的写法:`datetime.now(UTC)` 再摘掉 tzinfo —— 值一模一样,库里已有的行不受影响。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
