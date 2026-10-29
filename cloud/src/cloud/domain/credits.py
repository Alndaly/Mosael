"""积分账本(ADR 0088 §2):订阅、发放、到期、余额、预占与结算。

**余额是流水的结果。** 每一批积分(`CloudCreditBatch`)只记发了多少、何时到期;每一笔进出是 `CloudUsageEntry` 里带符号的一行,
挂在它动的那一批上。某一批还剩多少 = 这一批所有流水的和;没有可改写的余额列。

**不靠定时任务**:月度批次和到期清零在「读余额 / 预占」时按需补记(`catch_up`)—— 谁来用,就先把谁的账补到此刻。
所以一个从没回来过的用户,他的账也不会错,只是还没写下来。

一次调用的积分怎么动:

1. `reserve`:按上限估一个数,**先扣快到期的那批**,每扣一批写一行 `reserve`(负数)。不够就当场拒绝,说清差多少。
2. 完成后 `settle`:按实际用量算出该扣多少,多预占的那部分写成 `release`(正数)退回原来那几批;
   没成(上游失败、取消)就是 `settle(charged=0)`,全额退回。

这里的函数只 `flush`,**提交由调用方决定** —— 预占和建调用记录要在同一个事务里成或不成。
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud.errors import CloudError
from cloud.models import (
    CloudCreditBatch,
    CloudGatewayCall,
    CloudPlan,
    CloudSubscription,
    CloudUsageEntry,
    CloudUser,
)

#: 每种计费周期订多少个月。**积分一律按月发**,周期只决定订阅多久(ADR 0088 待拍板 #2)。
PERIOD_MONTHS = {"month": 1, "quarter": 3, "year": 12}


def add_months(moment: datetime, months: int) -> datetime:
    """日历上往后数几个月;落到不存在的日子(1 月 31 日 + 1 个月)取那个月的最后一天。"""
    total = moment.month - 1 + months
    year, month = moment.year + total // 12, total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def chat_cost(*, input_per_1k: int, output_per_1k: int, input_tokens: int, output_tokens: int) -> int:
    """一次对话值多少积分:输入、输出各按千 token 单价算,相加后**向上取整**(积分是最小单位,不欠零头)。"""
    return math.ceil((input_tokens * input_per_1k + output_tokens * output_per_1k) / 1000)


# ---------------------------------------------------------------- 发放


def _grant(
    db: Session,
    user_id: str,
    *,
    source: str,
    amount: int,
    granted_at: datetime,
    expires_at: datetime,
    subscription_id: str | None = None,
    note: str = "",
) -> CloudCreditBatch:
    batch = CloudCreditBatch(
        user_id=user_id,
        source=source,
        subscription_id=subscription_id,
        amount=amount,
        granted_at=granted_at,
        expires_at=expires_at,
        note=note,
    )
    db.add(batch)
    db.flush()
    db.add(CloudUsageEntry(user_id=user_id, batch_id=batch.id, kind="grant", delta=amount, created_at=granted_at))
    return batch


def subscribe(db: Session, user: CloudUser, plan: CloudPlan, *, at: datetime) -> CloudSubscription:
    """开通一个套餐(第 2 步由管理员手动开通;支付在第 3 步)。同一时间只有一个有效订阅:旧的先结束,已发的积分照用。

    第一批月度积分当场发。
    """
    for current in db.scalars(
        select(CloudSubscription).where(CloudSubscription.user_id == user.id, CloudSubscription.status == "active")
    ):
        current.status = "ended"
        current.ends_at = min(current.ends_at, at)
    subscription = CloudSubscription(
        user_id=user.id,
        plan_id=plan.id,
        status="active",
        started_at=at,
        ends_at=add_months(at, PERIOD_MONTHS[plan.period]),
        next_grant_at=at,
        created_at=at,
    )
    db.add(subscription)
    db.flush()
    catch_up(db, user.id, at=at)
    return subscription


def gift(db: Session, user: CloudUser, *, amount: int, days: int, note: str, at: datetime) -> CloudCreditBatch:
    """赠送一批积分(运营、补偿)。有效期由调用方给 —— 赠送的通常比月度短。"""
    if amount <= 0 or days <= 0:
        raise ValueError("amount and days must be positive")
    return _grant(db, user.id, source="gift", amount=amount, granted_at=at, expires_at=at + timedelta(days=days), note=note)


# ---------------------------------------------------------------- 把账补到此刻


def catch_up(db: Session, user_id: str, *, at: datetime) -> None:
    """补发到期该发的月度批次,把过了期还有剩的批次清零。幂等:同一时刻再跑一次什么都不写。"""
    subscriptions = db.scalars(
        select(CloudSubscription).where(CloudSubscription.user_id == user_id, CloudSubscription.status == "active")
    ).all()
    for subscription in subscriptions:
        plan = db.get(CloudPlan, subscription.plan_id)
        assert plan is not None  # 外键 RESTRICT:订阅还在,套餐就删不掉
        granted = db.scalar(
            select(func.count()).select_from(CloudCreditBatch).where(CloudCreditBatch.subscription_id == subscription.id)
        ) or 0
        while subscription.next_grant_at <= at and subscription.next_grant_at < subscription.ends_at:
            granted_at = subscription.next_grant_at
            _grant(
                db,
                user_id,
                source="plan",
                amount=plan.monthly_credits,
                granted_at=granted_at,
                expires_at=granted_at + timedelta(days=plan.credit_ttl_days),
                subscription_id=subscription.id,
            )
            granted += 1
            #: 一律从开通那一刻往后数第 N 个月,不从上一批往后推:1 月 31 日开通 → 2 月 28 日 → 3 月 31 日,日子不漂。
            subscription.next_grant_at = add_months(subscription.started_at, granted)
        if subscription.ends_at <= at:
            subscription.status = "ended"
    for batch, left in _remaining(db, user_id, expired=True, at=at):
        db.add(CloudUsageEntry(user_id=user_id, batch_id=batch.id, kind="expire", delta=-left, created_at=batch.expires_at))
    db.flush()


def _remaining(db: Session, user_id: str, *, expired: bool, at: datetime) -> list[tuple[CloudCreditBatch, int]]:
    """还有剩的批次及剩多少。`expired=False` 是此刻能用的(先到期的在前),`True` 是过了期还没清零的。"""
    left = func.coalesce(func.sum(CloudUsageEntry.delta), 0)
    when = CloudCreditBatch.expires_at <= at if expired else CloudCreditBatch.expires_at > at
    rows = db.execute(
        select(CloudCreditBatch, left)
        .join(CloudUsageEntry, CloudUsageEntry.batch_id == CloudCreditBatch.id)
        .where(CloudCreditBatch.user_id == user_id, when)
        .group_by(CloudCreditBatch.id)
        .having(left > 0)
        .order_by(CloudCreditBatch.expires_at, CloudCreditBatch.granted_at, CloudCreditBatch.id)
    ).all()
    return [(batch, int(amount)) for batch, amount in rows]


# ---------------------------------------------------------------- 读余额


@dataclass(frozen=True)
class BatchBalance:
    remaining: int
    expires_at: datetime
    source: str


@dataclass(frozen=True)
class Balance:
    total: int
    #: 先到期的在前 —— 界面据此说「N 积分将在 X 日到期」。
    batches: list[BatchBalance]
    #: 有效订阅的下一批何时发;没有订阅是 None。
    next_grant_at: datetime | None
    plan_name: str | None


def balance(db: Session, user_id: str, *, at: datetime) -> Balance:
    """此刻的余额(先把账补到此刻)。"""
    catch_up(db, user_id, at=at)
    usable = _remaining(db, user_id, expired=False, at=at)
    subscription = db.scalars(
        select(CloudSubscription)
        .where(CloudSubscription.user_id == user_id, CloudSubscription.status == "active")
        .order_by(CloudSubscription.started_at.desc())
    ).first()
    plan = db.get(CloudPlan, subscription.plan_id) if subscription else None
    next_grant = subscription.next_grant_at if subscription and subscription.next_grant_at < subscription.ends_at else None
    return Balance(
        total=sum(left for _, left in usable),
        batches=[BatchBalance(remaining=left, expires_at=batch.expires_at, source=batch.source) for batch, left in usable],
        next_grant_at=next_grant,
        plan_name=plan.name if plan else None,
    )


# ---------------------------------------------------------------- 预占与结算


def _lock_user(db: Session, user_id: str) -> None:
    """同一个用户的预占排队做:Postgres 上锁住用户那一行(SQLite 的写本来就是串行的,`FOR UPDATE` 在那里是空操作)。"""
    db.execute(select(CloudUser.id).where(CloudUser.id == user_id).with_for_update())


def reserve(db: Session, call: CloudGatewayCall, *, at: datetime) -> None:
    """为这次调用预占 `call.reserved` 积分:先扣快到期的那批。不够就抛 402,说清差多少、下一批何时发。"""
    _lock_user(db, call.user_id)
    catch_up(db, call.user_id, at=at)
    usable = _remaining(db, call.user_id, expired=False, at=at)
    available = sum(left for _, left in usable)
    if available < call.reserved:
        current = balance(db, call.user_id, at=at)
        raise CloudError(
            402,
            "insufficient_credits",
            needed=call.reserved,
            available=available,
            details={
                "needed": call.reserved,
                "available": available,
                "next_grant_at": current.next_grant_at.isoformat() if current.next_grant_at else None,
            },
        )
    owed = call.reserved
    for batch, left in usable:
        if owed == 0:
            break
        take = min(left, owed)
        db.add(CloudUsageEntry(user_id=call.user_id, batch_id=batch.id, kind="reserve", delta=-take, call_id=call.id,
                               created_at=at))
        owed -= take
    db.flush()


def settle(db: Session, call: CloudGatewayCall, *, charged: int, at: datetime) -> None:
    """按实际该扣的数结算:多预占的退回原来那几批(晚到期的先退)。`charged=0` 就是全额释放。

    该扣的超过预占的(上游报的输入比估的多)按预占封顶 —— 预占就是这次调用答应过的上限,不事后追扣。
    """
    if call.status != "reserved":
        raise ValueError(f"call {call.id} is already {call.status}")
    charged = max(0, min(charged, call.reserved))
    refund = call.reserved - charged
    #: 预占是先到期的先扣,退就倒过来:晚到期的先退(同一时刻写下的几行流水没有先后,按批次的到期时间定顺序)。
    taken = db.execute(
        select(CloudUsageEntry.batch_id, CloudUsageEntry.delta)
        .join(CloudCreditBatch, CloudCreditBatch.id == CloudUsageEntry.batch_id)
        .where(CloudUsageEntry.call_id == call.id, CloudUsageEntry.kind == "reserve")
        .order_by(CloudCreditBatch.expires_at.desc(), CloudCreditBatch.granted_at.desc(), CloudCreditBatch.id.desc())
    ).all()
    for batch_id, delta in taken:
        if refund == 0:
            break
        back = min(-delta, refund)
        db.add(CloudUsageEntry(user_id=call.user_id, batch_id=batch_id, kind="release", delta=back, call_id=call.id,
                               created_at=at))
        refund -= back
    call.charged = charged
    call.status = "settled" if charged > 0 else "released"
    call.finished_at = at
    db.flush()
