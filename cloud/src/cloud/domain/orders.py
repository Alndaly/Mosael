"""订单:下单拿二维码、到账发放、过期关单(ADR 0088 第 3 步,国内二维码预付)。

**「到账」只有一个入口** `settle_paid`:渠道的回调、桌面端轮询时的主动查单都走它。它锁住订单行再判断,所以同一笔钱无论
来几次(回调重发、回调和查单撞在一起)都只发放一次。渠道报的金额必须和下单那一刻的金额一致,对不上不发放、记在 `note`
里给运营;订单关了之后才到的付款照样发放 —— 钱收到了就给。

渠道怎么签名、怎么验签在 `cloud.payments`;这里只认「已经验过签的 `PaidNotice`」。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloud.domain import credits
from cloud.errors import CloudError
from cloud.models import CloudOrder, CloudPlan, CloudSubscription, CloudUser
from cloud.payments.base import ChannelUnavailable, PaidNotice, PaymentChannel

logger = logging.getLogger(__name__)

#: 二维码多久有效。过了就关单(之后才到的付款照样发放)。
ORDER_TTL = timedelta(minutes=30)
#: 关了的单还主动查多久:有人扫码后拖到最后一刻才付、回调又丢了,这段时间里查单还能兜住。
LATE_QUERY_WINDOW = timedelta(days=1)


def purchasable_plans(db: Session) -> list[CloudPlan]:
    """在线能买的套餐:在售、标了价。"""
    return list(
        db.scalars(
            select(CloudPlan)
            .where(CloudPlan.on_sale.is_(True), CloudPlan.price_cents.is_not(None))
            .order_by(CloudPlan.price_cents, CloudPlan.slug)
        )
    )


def create_order(
    db: Session,
    *,
    user: CloudUser,
    plan_slug: str,
    channel: PaymentChannel | None,
    at: datetime,
) -> CloudOrder:
    """下一笔单并向渠道要二维码。渠道没开(`channel` 为空)或渠道一时不可用都说清楚;下单失败不留半截订单(调用方回滚)。"""
    plan = db.scalar(select(CloudPlan).where(CloudPlan.slug == plan_slug))
    if plan is None or not plan.on_sale or plan.price_cents is None:
        raise CloudError(404, "plan_not_for_sale")
    if channel is None:
        raise CloudError(400, "payment_channel_unavailable")
    order = CloudOrder(
        user_id=user.id,
        plan_id=plan.id,
        amount_cents=plan.price_cents,
        currency=plan.currency,
        channel=channel.name,
        status="pending",
        created_at=at,
        expires_at=at + ORDER_TTL,
    )
    db.add(order)
    db.flush()
    try:
        qr = channel.create_qr(order_id=order.id, amount_cents=order.amount_cents,
                               subject=f"Mosael {plan.name}", expires_at=order.expires_at)
    except ChannelUnavailable as exc:
        logger.warning("下单要二维码失败(%s):%s", channel.name, exc)
        raise CloudError(503, "payment_channel_unavailable") from exc
    order.code_url = qr.code_url
    db.flush()
    return order


def settle_paid(db: Session, notice: PaidNotice, *, channel: str, at: datetime) -> CloudOrder | None:
    """渠道说这一笔付了(已验签):锁住订单行,没发放过就发放。认不出的订单号回 None(不是我们的单)。"""
    order = db.scalars(select(CloudOrder).where(CloudOrder.id == notice.order_id).with_for_update()).first()
    if order is None or order.channel != channel:
        logger.warning("渠道 %s 报了一笔不认识的订单 %s", channel, notice.order_id)
        return None
    if order.status == "paid":
        return order
    if notice.amount_cents != order.amount_cents:
        order.note = f"amount mismatch: channel says {notice.amount_cents}, order is {order.amount_cents}"[:300]
        logger.error("订单 %s 金额对不上:%s", order.id, order.note)
        db.flush()
        return order
    order.status = "paid"
    order.paid_at = notice.paid_at
    order.channel_trade_no = notice.channel_trade_no or order.channel_trade_no
    user = db.get(CloudUser, order.user_id) if order.user_id else None
    plan = db.get(CloudPlan, order.plan_id)
    if user is None or plan is None:
        # 付款到账时账号已经删了:钱照记,发放无从谈起 —— 留给运营退款。
        order.note = "paid after the account was deleted"
    else:
        order.subscription_id = credits.purchase(db, user, plan, at=at).id
    db.flush()
    return order


def refresh(db: Session, order: CloudOrder, channels: Mapping[str, PaymentChannel], *, at: datetime) -> CloudOrder:
    """桌面端轮询订单时:还没到账就主动问一次渠道(兜住丢了的回调);过了有效期还没付就关单。"""
    if order.status == "paid":
        return order
    channel = channels.get(order.channel)
    if channel is not None and at - order.created_at <= LATE_QUERY_WINDOW:
        try:
            notice = channel.query(order.id)
        except ChannelUnavailable as exc:
            logger.info("查单没问到(%s %s):%s", order.channel, order.id, exc)
            notice = None
        if notice is not None:
            settled = settle_paid(db, notice, channel=order.channel, at=at)
            if settled is not None:
                return settled
    if order.status == "pending" and at >= order.expires_at:
        order.status = "closed"
        db.flush()
    return order


def order_view(db: Session, order: CloudOrder) -> dict[str, object]:
    plan = db.get(CloudPlan, order.plan_id)
    subscription = db.get(CloudSubscription, order.subscription_id) if order.subscription_id else None
    return {
        "id": order.id,
        "status": order.status,
        "plan": {"slug": plan.slug, "name": plan.name, "period": plan.period} if plan else None,
        "amount_cents": order.amount_cents,
        "currency": order.currency,
        "channel": order.channel,
        #: 只在等付款时给二维码:付了、关了再给就是一张扫了也没用的码。
        "code_url": order.code_url if order.status == "pending" else None,
        "created_at": order.created_at.isoformat(),
        "expires_at": order.expires_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        #: 到账后发放的那个订阅现在到哪天 —— 续费是顺延,不会当场多一批积分,界面要说的是「有效期到哪天」。
        "subscription_ends_at": subscription.ends_at.isoformat() if subscription else None,
    }
