"""一轮**进行中**的步骤,落库的那一份。

`domain/agent/stream` 里的 timeline 是进程内的:后端一重启,线程即死,那一轮做过什么也跟着没了 ——
启动收尾只能补一句「已中断」,用户看不到子代理跑到哪、工具调用做成了没有。维护者 2026-10-18 拍板
(#5):接受每次工具事件的 DB 写,换回这份过程。

**为什么是新表,不是写进消息 payload。** 消息会整条读出(对话列表、轨迹、回看),`payload.timeline`
是一个随轮次增长的数组 —— 每个工具事件都改一次它,等于每调一次工具就重写整条消息的 JSON,而写放大
不只落在写:读的人也要重新解析越来越大的 payload。这里是一次 append 一小行;收尾时照旧把折叠好的
时间线写进消息 payload(形状不变,UI 不用改),然后把这一轮的行删掉。

**写多少。** 只写工具卡 / 子代理的每一步(工具开始、工具结束、子智能体内部一步、后台子智能体的存档回填),
不写正文和思考的增量 —— 那是逐 token 的,一次对话就能写出几万行,而重启之后要回答的问题不是
「它当时吐了哪些字」,是「它做到哪一步」。正文/思考照旧随轮次收尾落进消息 payload。

**顺序与幂等。** `(turn_id, seq)` 唯一。`seq` 沿用流状态里那个每改一次就加一的计数,所以事件在
库里的先后就是它们发生的先后;同一个 `(turn_id, seq)` 被重写一次是覆盖,不是多一行。

**事务边界。** 一个事件一个短事务,只 insert 一行就提交 —— 不把整轮包在一个事务里(那一轮可能跑几分钟),
也不持有连接等模型。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import JSON, Column, DateTime, Index, Integer, MetaData, String, Table, UniqueConstraint, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.model_base import new_id, now

#: **不进 `Base.metadata`。** 这张表由迁移建(`migrations._migrate_agent_turn_events_table`),
#: 不从 `create_all` 走:测试 `tests/schema_baseline.json` 记的是「老库出生时的表」,新表往那里补一笔
#: 需要解释,而这张表与既有领域表没有关系(也不设外键 —— 事件是过程日志,会话删了就该由清理收走,
#: 不该让 DROP TABLE 的顺序变成它的负担)。
TURN_EVENTS = Table(
    "agent_turn_events",
    MetaData(),
    Column("id", String(64), primary_key=True),
    Column("session_id", String(64), nullable=False),
    Column("turn_id", String(64), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("kind", String(32), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False),
    UniqueConstraint("turn_id", "seq", name="uq_agent_turn_events_turn_seq"),
    Index("ix_agent_turn_events_session", "session_id", "created_at"),
)


def _row(*, session_id: str, turn_id: str, seq: int, kind: str, payload: dict) -> dict:
    return {
        "id": new_id(),
        "session_id": session_id,
        "turn_id": turn_id,
        "seq": seq,
        "kind": kind,
        "payload": payload,
        "created_at": now(),
    }


def record_turn_event(*, session_id: str, turn_id: str, seq: int, kind: str, payload: dict) -> None:
    """追加一个事件。**自己的短事务** —— 调用方(流)不持有也不该持有数据库会话。"""
    values = _row(session_id=session_id, turn_id=turn_id, seq=seq, kind=kind, payload=payload)
    with SessionLocal() as db:
        statement = sqlite_insert(TURN_EVENTS).values(**values)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[TURN_EVENTS.c.turn_id, TURN_EVENTS.c.seq],
                set_={"kind": statement.excluded.kind, "payload": statement.excluded.payload},
            )
        )
        db.commit()


def latest_turn_id(db: Session, session_id: str) -> str | None:
    """这个会话最后动过的那一轮。正常收尾会把行删掉,所以留下来的那一轮就是被中断的那一轮。"""
    return db.execute(
        select(TURN_EVENTS.c.turn_id)
        .where(TURN_EVENTS.c.session_id == session_id)
        .order_by(TURN_EVENTS.c.created_at.desc(), TURN_EVENTS.c.seq.desc())
        .limit(1)
    ).scalar()


def turn_events(db: Session, session_id: str) -> list[dict]:
    """这个会话最后一轮的原始事件,按发生顺序。测试与收尾读取都走这里。"""
    turn_id = latest_turn_id(db, session_id)
    if not turn_id:
        return []
    rows = db.execute(
        select(TURN_EVENTS.c.seq, TURN_EVENTS.c.kind, TURN_EVENTS.c.payload)
        .where(TURN_EVENTS.c.turn_id == turn_id)
        .order_by(TURN_EVENTS.c.seq)
    ).all()
    return [{"seq": row.seq, "kind": row.kind, "payload": row.payload} for row in rows]


def timeline_for_session(db: Session, session_id: str) -> list[dict]:
    """这一轮已经发生过的过程,收成消息 payload 里 `timeline` 的形状。

    事件存的是**那一刻那张卡的完整快照**(工具结束时整张卡都变了,不是只多一个字段),所以同一张卡
    以最后一次快照为准,位置按第一次出现 —— 重启之后看到的工具卡因此带着真实的耗时和结果。
    子代理的存档回填也是同一个父卡的新快照,靠 `tool.id` 认出来。
    """
    return collapse_timeline([event["payload"] for event in turn_events(db, session_id)])


def collapse_timeline(items: list[dict]) -> list[dict]:
    collapsed: list[dict] = []
    positions: dict[tuple[str, str], int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        kind = str(item.get("type") or "")
        tool_id = str(tool.get("id") or "") if isinstance(tool, dict) else ""
        if kind not in {"tool", "subtool"} or not tool_id:
            continue
        key = (kind, tool_id)
        position = positions.get(key)
        if position is None:
            positions[key] = len(collapsed)
            collapsed.append(item)
        else:
            collapsed[position] = item
    return collapsed


def delete_turn_events(db: Session, turn_id: str) -> int:
    """这一轮收尾了(成功、失败、被重启拨回都一样):中间过程删掉,消息 payload 才是唯一的记录。

    调用方持有事务(重启收尾是一次用例、一起提交);**自己收尾的一轮**用下面的
    `discard_turn_events` —— 领域层不提交事务(见 tests/test_use_case_boundaries_ratchet)。
    """
    if not turn_id:
        return 0
    return db.execute(delete(TURN_EVENTS).where(TURN_EVENTS.c.turn_id == turn_id)).rowcount or 0


def discard_turn_events(turn_id: str) -> None:
    """正常收尾的一轮删掉自己的过程事件 —— **自己的短事务**,和 `record_turn_event` 对称。"""
    if not turn_id:
        return
    with SessionLocal() as db:
        delete_turn_events(db, turn_id)
        db.commit()


def prune_turn_events(db: Session, *, older_than_days: int = 7) -> int:
    """兜底清理:**只收真正的旧行**。

    正常的一轮在收尾时就把自己的行删了;重启中断的那一轮在拨回时删。会留下来的只有「收尾代码没跑到、
    会话也没在跑」的行(进程被杀在收尾中间),按天收走,不让这张表无限增长。7 天是为了不碰任何
    还在跑的一轮 —— 它的事件是分钟级的。
    """
    cutoff = now() - timedelta(days=older_than_days)
    return db.execute(delete(TURN_EVENTS).where(TURN_EVENTS.c.created_at < cutoff)).rowcount or 0
