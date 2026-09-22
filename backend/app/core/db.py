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


def pool_capacity() -> int:
    """这个池子同时能给出多少条连接 —— `pool_size + max_overflow`。

    **从池子自己问出来,不另写一个数。** 写死的话,改 `create_engine` 的人不会知道还有第二处
    要跟着改,而不一致的表现是 `TimeoutError: QueuePool limit of size 5 overflow 10 reached`
    被原样记进 job.error:用户看到一句 SQLAlchemy 的英文。
    """
    pool = engine.pool
    return int(pool.size()) + int(getattr(pool, "_max_overflow", 0) or 0)


#: 留给"不走工作流引擎"的那些人:HTTP 请求、任务总线、回收线程、定时器。
#:
#: 工作流引擎是全仓唯一会**同时**开很多会话的一层,所以它必须按池子的容量派发 —— 而不是按
#: 一个和池子无关的并发数。此前三个常数各写在三个文件里(`MAX_PARALLEL_NODES = 8`、
#: `LOOP_FOREACH_MAX_CONCURRENCY = 4`、`MAX_NEST_DEPTH = 8`),每一个单看都克制,**而它们是
#: 相乘的,没有任何一处写下它们的乘积要小于什么**。小图跑起来一切正常,规模上去才崩,
#: 而崩的那一刻错误指向的是随便哪个节点。
POOL_RESERVE = 5


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
