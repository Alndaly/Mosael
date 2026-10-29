"""在线购买(ADR 0088 第 3 步,国内二维码预付):套餐、下单、订单状态、渠道回调。

- `GET /plans`:在线能买的套餐和这个部署开了哪些支付渠道(公开读);
- `POST /orders`:下单,回二维码内容(浏览器会话、桌面端设备令牌都认);
- `GET /orders`、`GET /orders/{id}`:我的订单。读单个订单时,还没到账就主动问一次渠道(兜住丢了的回调);
- `POST /payments/{channel}/notify`:渠道的异步通知。**不认人**(渠道不是登录用户),靠验签认渠道;回给它它要的那句。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from cloud.api.deps import CurrentUser, DbSession
from cloud.domain import orders
from cloud.errors import CloudError
from cloud.models import CloudOrder, now
from cloud.payments.base import NotifyRejected

router = APIRouter(tags=["orders"])


@router.get("/plans")
def list_plans(request: Request, db: DbSession) -> dict[str, object]:
    return {
        "plans": [
            {
                "slug": plan.slug,
                "name": plan.name,
                "period": plan.period,
                "monthly_credits": plan.monthly_credits,
                "credit_ttl_days": plan.credit_ttl_days,
                "price_cents": plan.price_cents,
                "currency": plan.currency,
            }
            for plan in orders.purchasable_plans(db)
        ],
        "channels": sorted(request.app.state.payment_channels),
    }


class OrderIn(BaseModel):
    plan: str = Field(min_length=1, max_length=64)
    channel: Literal["alipay", "wechat"]


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, request: Request, user: CurrentUser, db: DbSession) -> dict[str, object]:
    order = orders.create_order(
        db, user=user, plan_slug=body.plan, channel=request.app.state.payment_channels.get(body.channel), at=now()
    )
    db.commit()
    return {"order": orders.order_view(db, order)}


@router.get("/orders")
def list_orders(user: CurrentUser, db: DbSession) -> dict[str, object]:
    found = db.scalars(
        select(CloudOrder).where(CloudOrder.user_id == user.id).order_by(CloudOrder.created_at.desc()).limit(50)
    ).all()
    return {"orders": [orders.order_view(db, order) for order in found]}


@router.get("/orders/{order_id}")
def get_order(order_id: str, request: Request, user: CurrentUser, db: DbSession) -> dict[str, object]:
    order = db.get(CloudOrder, order_id)
    if order is None or order.user_id != user.id:
        raise CloudError(404, "order_not_found")
    orders.refresh(db, order, request.app.state.payment_channels, at=now())
    db.commit()
    return {"order": orders.order_view(db, order)}


@router.post("/payments/{channel}/notify")
async def payment_notify(channel: str, request: Request) -> Response:
    """渠道的异步通知。验签不过回失败(渠道会重发,我们不发放);验过了的,不管是不是我们认识的单都回「收到」,免得它一直重发。"""
    payment = request.app.state.payment_channels.get(channel)
    if payment is None:
        raise CloudError(404, "not_found")
    body = await request.body()
    with request.app.state.db.session() as db:
        try:
            notice = payment.parse_notify(headers=dict(request.headers), body=body, at=now())
        except NotifyRejected:
            ack = payment.ack(False)
            return Response(ack.body, status_code=ack.status_code, media_type=ack.media_type)
        if notice is not None:
            orders.settle_paid(db, notice, channel=channel, at=now())
            db.commit()
    ack = payment.ack(True)
    return Response(ack.body, status_code=ack.status_code, media_type=ack.media_type)
