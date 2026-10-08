"""数据库的**底座**:引擎、会话、Base。

`app/core` 是最底层 —— 谁都可以 import 它,它不 import 任何人。所以这里**不放迁移**:
迁移要认识每一个领域(声音克隆的 venv 往哪搬、插件表怎么拆),而这个模块被二十几处
import。两个方向相反的职责挤在一起时,迁移只能靠写在函数体里的 `from app.domain import …`
硬撑——那不是技巧,是"层分错了"的自白。迁移住在 `app/db/migrations.py`,它在依赖序的顶端。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


#: 写的时候碰上别人攥着写锁,最多等多久(SQLite 的 busy_timeout)。全库只有这一个等锁的预算,谁写都用它。
#:
#: 此前是 5 秒 —— SQLite 示例里的那个数,没人为这个应用算过。攥锁的时长不只是那几句写本身:从第一句写到提交之间的
#: Python 代码、拿 GIL 的排队、提交时的 fsync,机器一忙全都拉长。测试全量跑时量到过攥 2.35 秒的正常事务,
#: 5 秒只有两倍余量,工作流节点写笔记偶尔就等满了失败 —— 前面几步付费调用的结果跟着白花。等不起的只有交互,
#: 而 30 秒仍在请求超时之内;真攥这么久的是 bug,下面的诊断会点名它。
LOCK_WAIT_SECONDS = 30.0


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute(f"PRAGMA busy_timeout={int(LOCK_WAIT_SECONDS * 1000)}")
    cursor.close()


# --------------------------------------------------------------------------------------
# 写锁:保存点不做最外层;谁攥着、攥了多久说得出来
# --------------------------------------------------------------------------------------
#
# pysqlite 只在第一句 INSERT / UPDATE / DELETE 之前自己 `BEGIN`(延迟事务),之前的读各自是一个自动提交的快照。
# 所以「先读后写」的会话第一句写时手上没有读事务,碰上别人攥着写锁就按上面的预算排队 —— 工作流节点、请求都是这样。
#
# 排不了队、当场报 database is locked 的只有一种:**这条连接已经开着读事务,再要升级成写**。SQLite 不让它排队
# (排到了快照也旧了),busy_timeout 不起作用。在这个应用里走到这一步的是「事务里第一句就是保存点」:SAVEPOINT
# 不是 pysqlite 认的写,它不先 BEGIN,SQLite 把 SAVEPOINT 当成一个延迟事务的开头;保存点里先读后写,就是升级。
# 这样开头的保存点还有第二个毛病:它是最外层,RELEASE 当场提交,外层之后回滚也收不回来。


@event.listens_for(engine, "savepoint")
def _a_savepoint_never_starts_the_transaction(conn, _name) -> None:
    """事务里还没写过就开保存点:先 `BEGIN IMMEDIATE`,保存点开在它里面。

    开头就拿写锁,拿的时候按 busy_timeout 排队;拿到之后读到的是最新的,写不用再升级。保存点只包写的那几步
    (插件登记、默认网络配置建行、改名搬迁、确认卡演练),先拿锁不会让只读的路径排队。
    """
    if not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


#: 一个写事务攥写锁超过这么久,放手时记一条警告:是谁、从哪一行开始写的。这段时间里别的写入都在排队。
LONG_WRITE_SECONDS = 2.0
_WRITE_VERBS = ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE")
_APP_ROOT = str(Path(__file__).parents[1])


@dataclass(frozen=True)
class _Writer:
    """攥着写锁的一个事务:第一句写在什么时候、哪个线程、哪一句、应用里从哪一行走过来的。"""

    connection: Any
    since: float
    thread: str
    statement: str
    where: str

    def describe(self, at: float) -> str:
        return f"线程 {self.thread} 攥了 {at - self.since:.1f} 秒(第一句写 {self.statement},从 {self.where} 开始)"


#: DBAPI 连接的 id → 它手上的写事务。只用来说清楚是谁,不参与任何判断。
_writers: dict[int, _Writer] = {}
_statement_started = threading.local()


def _where() -> str:
    """应用里离这里最近的几帧(由内向外),跳过本模块和 SQLAlchemy。"""
    frames: list[str] = []
    frame = sys._getframe(1)
    while frame is not None and len(frames) < 4:
        filename = frame.f_code.co_filename
        if filename.startswith(_APP_ROOT) and filename != __file__:
            frames.append(f"{filename[len(_APP_ROOT) + 1:]}:{frame.f_lineno} {frame.f_code.co_name}")
        frame = frame.f_back
    return " ← ".join(frames) or "应用以外"


@event.listens_for(engine, "before_cursor_execute")
def _note_when_the_statement_started(_conn, _cursor, _statement, _parameters, _context, _executemany) -> None:
    _statement_started.at = time.monotonic()


@event.listens_for(engine, "after_cursor_execute")
def _note_the_first_write(conn, _cursor, statement, _parameters, _context, _executemany) -> None:
    dbapi = conn.connection.driver_connection
    if id(dbapi) in _writers or not statement.lstrip()[:15].upper().startswith(_WRITE_VERBS):
        return
    if dbapi.in_transaction:  # 自动提交下的一句写,做完就放了锁
        first_line = " ".join(statement.split())[:80]
        _writers[id(dbapi)] = _Writer(dbapi, time.monotonic(), threading.current_thread().name, first_line, _where())


def _write_ends(dbapi) -> None:
    writer = _writers.pop(id(dbapi), None)
    if writer is None:
        return
    held = time.monotonic() - writer.since
    if held > LONG_WRITE_SECONDS:
        logger.warning("写锁攥了 %.1f 秒才放,这段时间里别的写入都在排队:%s", held, writer.describe(time.monotonic()))


event.listen(engine, "commit", lambda conn: _write_ends(conn.connection.driver_connection))
event.listen(engine, "rollback", lambda conn: _write_ends(conn.connection.driver_connection))
#: 会话没提交就关了:连接还回池子时回滚,写事务在这里结束。
event.listen(engine.pool, "reset", lambda dbapi, _record, _state: _write_ends(dbapi))


def _still_writing(writer: _Writer) -> bool:
    try:
        return bool(writer.connection.in_transaction)
    except Exception:  # noqa: BLE001 — 连接已经关了
        return False


@event.listens_for(engine, "handle_error")
def _name_who_holds_the_lock(context) -> None:
    """database is locked:在异常上(和日志里)写清是哪一种、写锁在谁手上。

    等满了上限 —— 有人攥得太久,点名是谁;当场就失败 —— 这条连接自己开着读事务(见上面那段),别人攥着与否都一样。
    """
    if "database is locked" not in str(context.original_exception):
        return
    waited = time.monotonic() - getattr(_statement_started, "at", time.monotonic())
    me = threading.current_thread().name
    mine = id(context.connection.connection.driver_connection) if context.connection is not None else None
    at = time.monotonic()
    holders = [writer for key, writer in list(_writers.items()) if key != mine and _still_writing(writer)]
    immediate = waited < LOCK_WAIT_SECONDS / 2
    if immediate:
        kind = f"当场失败(只等了 {waited:.2f} 秒):这条连接已经开着读事务、要升级成写,SQLite 不让它排队"
    else:
        kind = f"等满了 {waited:.1f} 秒还没等到写锁"
    if holders:
        named = "写锁在 " + ";".join(writer.describe(at) for writer in holders)
        if any(writer.thread == me for writer in holders):
            named += " —— 攥着它的就是这个线程自己的另一个会话,它等不到自己放手"
    elif immediate:
        named = "没有人攥着写锁:是它读到的快照旧了(读过之后别的连接提交过)"
    else:
        named = "这个进程里没有登记到攥着写锁的事务(锁在别的进程手里)"
    note = f"{me} 写 {' '.join((context.statement or '').split())[:80]} 时{kind}。{named}"
    logger.warning("database is locked:%s", note)
    (context.sqlalchemy_exception or context.original_exception).add_note(note)


def session_scope() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
