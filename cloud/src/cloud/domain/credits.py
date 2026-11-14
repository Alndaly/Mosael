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
    CloudGenerationJob,
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


#: 价格分量的计量分母。token 按千;image / second / request 按个。
UNIT_SCALE = {"token_input": 1000, "token_output": 1000}


def cost_for_units(units: dict[str, int], usage: dict[str, int]) -> int:
    """用量事实 × 单价分量;没有用量的分量不计,总和向上取整。"""
    total = sum(
        usage.get(unit, 0) * rate / UNIT_SCALE.get(unit, 1)
        for unit, rate in units.items()
        if rate
    )
    return math.ceil(total) if total else 0


def chat_cost(*, input_per_1k: int, output_per_1k: int, input_tokens: int, output_tokens: int) -> int:
    """兼容旧调用点的 token 计费;新代码走 `cost_for_units`。"""
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
    entry_kind: str = "grant",
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
    db.add(CloudUsageEntry(user_id=user_id, batch_id=batch.id, kind=entry_kind, delta=amount, created_at=granted_at))
    return batch


def subscribe(db: Session, user: CloudUser, plan: CloudPlan, *, at: datetime) -> CloudSubscription:
    """**管理员**开通一个套餐(`cloud.cli subscribe`):替换 —— 现有的有效订阅先结束(已发的积分照用),再开这一个。

    这是运维动作(内测、补偿、纠错),不涉及用户付过的钱;花钱买的走 `purchase`,那里什么都不作废。第一批月度积分当场发。
    """
    for current in db.scalars(
        select(CloudSubscription).where(CloudSubscription.user_id == user.id, CloudSubscription.status == "active")
    ):
        current.status = "ended"
        current.ends_at = min(current.ends_at, at)
    return _start(db, user, plan, at=at)


def _start(db: Session, user: CloudUser, plan: CloudPlan, *, at: datetime) -> CloudSubscription:
    """从此刻开一个订阅、当场发第一批月度积分。不碰别的订阅。"""
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


def purchase(db: Session, user: CloudUser, plan: CloudPlan, *, at: datetime) -> CloudSubscription:
    """买了这个套餐的一个周期(ADR 0088 第 3 步,预付)。**花钱买的什么都不作废**:

    - **同一套餐还在有效期内** → 顺延:到期日往后加一个周期,月度批次照开通那天的日历继续发(不另起一条订阅);
    - 另一个套餐、或这个套餐已经过期 → 从此刻再开一个订阅,**和现有的同时生效**,各自按月发积分、积分合在一个池子里用,
      各自到期。升级补差价不做。(此前是「换套餐就结束旧的」—— 真界面实测时,刚顺延到两年后的年付套餐被一笔月付直接作废。)
    """
    catch_up(db, user.id, at=at)
    current = db.scalars(
        select(CloudSubscription).where(
            CloudSubscription.user_id == user.id,
            CloudSubscription.status == "active",
            CloudSubscription.plan_id == plan.id,
            CloudSubscription.ends_at > at,
        )
    ).first()
    if current is None:
        return _start(db, user, plan, at=at)
    current.ends_at = add_months(current.ends_at, PERIOD_MONTHS[plan.period])
    db.flush()
    catch_up(db, user.id, at=at)
    return current


def revoke_purchase(db: Session, subscription: CloudSubscription, plan: CloudPlan, *, at: datetime) -> None:
    """退款收回这一笔买下的**一个周期**(ADR 0088 后续修正 2026-11-14)。

    - 订阅的到期日往前退一个周期;退完已经不在未来 → 订阅此刻结束;
    - 落在被收回那段时间里发的批次,没用完的作废(追加 `adjust` 流水,不改批次);之前那段时间发的照用 —— 那是付过钱的部分。

    新开的订阅整段被收回(立刻结束、余下积分作废);续费顺延收回的是还没到的那段,眼下的权益不受影响,只是到期日提前。
    此前「标记退款」只记一笔:订阅照样有效、积分照发,退了款的人继续用。
    """
    _lock_user(db, subscription.user_id)
    catch_up(db, subscription.user_id, at=at)
    cut = add_months(subscription.ends_at, -PERIOD_MONTHS[plan.period])
    if cut <= at:
        subscription.status = "ended"
        subscription.ends_at = at
    else:
        subscription.ends_at = cut
    left = func.coalesce(func.sum(CloudUsageEntry.delta), 0)
    revoked = db.execute(
        select(CloudCreditBatch, left)
        .join(CloudUsageEntry, CloudUsageEntry.batch_id == CloudCreditBatch.id)
        .where(CloudCreditBatch.subscription_id == subscription.id, CloudCreditBatch.granted_at >= cut)
        .group_by(CloudCreditBatch.id)
        .having(left > 0)
    ).all()
    for batch, remaining in revoked:
        db.add(CloudUsageEntry(user_id=subscription.user_id, batch_id=batch.id, kind="adjust", delta=-int(remaining),
                               created_at=at))
    db.flush()


def gift(db: Session, user: CloudUser, *, amount: int, days: int, note: str, at: datetime) -> CloudCreditBatch:
    """赠送一批积分(运营、补偿)。有效期由调用方给 —— 赠送的通常比月度短。"""
    if amount <= 0 or days <= 0:
        raise ValueError("amount and days must be positive")
    return _grant(db, user.id, source="gift", amount=amount, granted_at=at, expires_at=at + timedelta(days=days), note=note)


def adjust(db: Session, user: CloudUser, *, delta: int, days: int, note: str, at: datetime) -> None:
    """管理台人工调整:正数发一批(gift 来源),负数从可用批次里按先到期顺序扣。

    负数不能扣到负余额;也不改写批次本身的金额,只追加 `adjust` 流水。"""
    if delta == 0:
        raise CloudError(400, "invalid_adjustment")
    _lock_user(db, user.id)
    catch_up(db, user.id, at=at)
    if delta > 0:
        if days <= 0:
            raise CloudError(400, "invalid_adjustment")
        _grant(
            db, user.id, source="gift", amount=delta, granted_at=at,
            expires_at=at + timedelta(days=days), note=note, entry_kind="adjust",
        )
        db.flush()
        return
    usable = _remaining(db, user.id, expired=False, at=at)
    available = sum(left for _, left in usable)
    if -delta > available:
        raise CloudError(
            400,
            "insufficient_credits",
            needed=-delta,
            available=available,
            details={"needed": -delta, "available": available},
        )
    owed = -delta
    for batch, left in usable:
        if owed == 0:
            break
        take = min(left, owed)
        db.add(CloudUsageEntry(user_id=user.id, batch_id=batch.id, kind="adjust", delta=-take, created_at=at))
        owed -= take
    db.flush()


# ---------------------------------------------------------------- 把账补到此刻


def catch_up(db: Session, user_id: str, *, at: datetime) -> None:
    """补发到期该发的月度批次,把过了期还有剩的批次清零。幂等:同一时刻再跑一次什么都不写。

    **先锁住用户行。** 读余额(桌面端查余额、聊天结算、管理台)、预占、购买都会调到这里;此前只有预占和人工调整先锁,发放那一刻
    并发进来的两个请求都看到「该发了」,各发一批(过期清零也各写一遍)。批次表上的唯一约束是最后一道兜底(迁移 0027)。
    """
    _lock_user(db, user_id)
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
    #: 这个套餐到哪天:续费是把它往后顺延、积分不会当场多 —— 买完之后界面靠它说「有效期到哪天」。
    plan_ends_at: datetime | None


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
        plan_ends_at=subscription.ends_at if subscription else None,
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


def settle(db: Session, call: CloudGatewayCall, *, charged: int, at: datetime) -> bool:
    """按实际该扣的数结算:多预占的退回原来那几批(晚到期的先退)。`charged=0` 就是全额释放。交回这一次是否真的结了。

    该扣的超过预占的(上游报的输入比估的多)按预占封顶 —— 预占就是这次调用答应过的上限,不事后追扣。

    **先锁住这一笔再判断,已经结过的什么都不做。** 结算有好几条路(worker 跑完 / 失败、用户取消、流断开的 finally、陈旧预占回收),
    此前只在内存里看 `status == "reserved"`:两条路同时到,两边都看到「还没结」,各写一遍退回流水 —— 凭空多出积分。
    """
    #: 先把调用方刚记上的用量(token 数等)写进去,再加锁重读 —— 直接重读会把还没写库的改动丢掉。
    db.flush()
    db.refresh(call, with_for_update=True)
    if call.status != "reserved":
        return False
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
    return True


#: 预占多久还没结算就算卡住了。聊天一次最长也就几分钟;生成任务由它自己的状态管(见下),不按这个时限。
STALE_RESERVATION = timedelta(minutes=30)


def release_stale(db: Session, *, at: datetime, older_than: timedelta = STALE_RESERVATION) -> int:
    """回收卡住的预占:超过时限还是 `reserved`、又不属于一个还在跑的生成任务的调用,全额释放。交回释放了几笔。

    怎么会卡:非流式聊天读回包时连接断了、流式响应中途进程退出、worker 在结算前崩了 —— 结算那一步没走到,这部分积分就一直
    被占着,余额看着少了一截。全额释放是对用户有利的那一边:上游有没有真的算钱我们此刻不知道,不替用户猜。
    """
    running = select(CloudGenerationJob.id).where(
        CloudGenerationJob.call_id == CloudGatewayCall.id, CloudGenerationJob.status.not_in(("succeeded", "failed", "cancelled"))
    )
    stuck = db.scalars(
        select(CloudGatewayCall)
        .where(CloudGatewayCall.status == "reserved", CloudGatewayCall.created_at < at - older_than, ~running.exists())
        .order_by(CloudGatewayCall.created_at)
        .limit(200)
    ).all()
    return sum(1 for call in stuck if settle(db, call, charged=0, at=at))

