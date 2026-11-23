"""认领 / 租约协议:一个外部执行器领走一行活儿,靠心跳续着;不续了就到点,由后端收尾。

作用在带三列 `lease_worker / lease_token / lease_expires_at` 和一列 `status` 的表上(任务总线的 `Job`、浏览器的
`BrowserAction`)。此前两处各写一份:租约时长定义两次,令牌一处 `token_hex(24)`、一处 `uuid4().hex`,令牌比对一处
常数时间、一处 `!=`;过期判定一处锁行复核、一处查完就判 —— 后者让「心跳刚续上」的动作被误判失败。

这里收的是**协议本身**:多长、怎么发令牌、怎么认领、怎么续、怎么验、什么叫到点了。**到点之后怎么办**留给各自:
任务要走完成状态机、记事件、连带取消子任务,所以逐行锁住复核(`still_expired`);浏览器动作只翻一个状态,
用一条带条件的 UPDATE(`expired_rows` 当 WHERE)—— 两种写法都和续约(`renew`)在数据库里互斥。

发布任务(`PublishTask`)是另一套(按 worker 心跳、没有令牌),没接进来(架构体检拍板 C)。
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, update
from sqlalchemy.orm import Session

from app.db.models import now

#: 一次认领 / 续约管多久。执行器 20 秒心跳一次,三次没来才算丢了。
LEASE_SECONDS = 60


def expires_at(stamp: datetime | None = None) -> datetime:
    return (stamp or now()) + timedelta(seconds=LEASE_SECONDS)


def new_token() -> str:
    return secrets.token_hex(24)


def claim(db: Session, model: Any, row_id: str, *, worker: str, from_statuses: Iterable[str], values: Mapping[str, Any] | None = None) -> str | None:
    """把这一行从 `from_statuses` 翻成 running 并落租约三件套;回这次的令牌,被别人抢先了回 None。

    CAS:WHERE 里带着「还在 from_statuses」,两个执行器同时领同一行只有一个改得动。
    """
    token = new_token()
    changed = db.execute(
        update(model)
        .where(model.id == row_id, model.status.in_(tuple(from_statuses)))
        .values(
            status="running",
            lease_worker=(worker or "")[:64] or None,
            lease_token=token,
            lease_expires_at=expires_at(),
            **dict(values or {}),
        )
    ).rowcount
    return token if changed else None


def renew(db: Session, model: Any, *, worker: str, claims: Iterable[tuple[str, str]]) -> list[str]:
    """心跳续约。回**真的续上了**的那些 id —— 没续上的(不是你领的、令牌不对、已经到点),执行器该停手。

    带条件的 UPDATE:续约和到点判定(`expired_rows` 那条 WHERE)在数据库里互斥。
    """
    stamp = now()
    renewed: list[str] = []
    for row_id, token in claims:
        count = db.execute(
            update(model)
            .where(
                model.id == row_id,
                model.status == "running",
                model.lease_worker == ((worker or "")[:64] or None),
                model.lease_token == token,
                model.lease_expires_at > stamp,
            )
            .values(lease_expires_at=expires_at(stamp))
        ).rowcount
        if count:
            renewed.append(row_id)
    return renewed


def expired_rows(model: Any, stamp: datetime) -> ColumnElement[bool]:
    """「在跑、租约到点了」—— 到点判定的唯一判据。"""
    return and_(model.status == "running", model.lease_expires_at.is_not(None), model.lease_expires_at <= stamp)


def still_expired(row: Any, stamp: datetime) -> bool:
    """锁住、重读之后再问一次:查出候选和拿到锁之间,心跳可能刚把租约续上。"""
    return row.status == "running" and row.lease_expires_at is not None and row.lease_expires_at <= stamp


def holds(row: Any, token: str | None) -> bool:
    """回报带的令牌是不是这一行现在的令牌(常数时间比较)。行上没有令牌 = 没有人领过,不算持有。"""
    #: 按字节比:`compare_digest` 收到含非 ASCII 的 str 会抛 TypeError,而令牌是回报方随便给的。
    return bool(row.lease_token) and secrets.compare_digest(str(row.lease_token).encode(), (token or "").encode())
