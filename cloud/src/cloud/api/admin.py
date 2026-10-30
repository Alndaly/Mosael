"""MosaelCloud 管理端 API。

**只接受浏览器会话 + `role=admin`**。设备令牌不能管理部署。
响应全部显式组装,不含密码哈希、设备令牌或上游 Key。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from cloud.admin import service
from cloud.admin.schemas import (
    ChannelIn,
    ChannelPatch,
    GiftIn,
    ModelIn,
    ModelPatch,
    PlanIn,
    PlanPatch,
    PriceIn,
    RoleIn,
    SubscribeIn,
)
from cloud.api.deps import CurrentAdmin, CurrentConfig, DbSession

router = APIRouter(tags=["admin"])


@router.get("/admin/me")
def admin_me(user: CurrentAdmin) -> dict[str, object]:
    from cloud.domain.identity import account_user

    return {"user": account_user(user)}


@router.get("/admin/overview")
def admin_overview(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return service.overview(db)


@router.get("/admin/users")
def admin_users(
    _user: CurrentAdmin,
    db: DbSession,
    q: str = Query(default="", max_length=200),
) -> dict[str, object]:
    return {"users": service.list_users(db, query=q)}


@router.get("/admin/users/{user_id}")
def admin_user(user_id: str, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"user": service.user_detail(db, user_id)}


@router.post("/admin/users/{user_id}/role")
def admin_user_role(user_id: str, body: RoleIn, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.set_role(db, user_id, body.role)
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/credits")
def admin_user_credits(user_id: str, body: GiftIn, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.gift(db, user_id, amount=body.credits, days=body.days, note=body.note)
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/subscriptions")
def admin_user_subscription(user_id: str, body: SubscribeIn, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.subscribe(db, user_id, plan_slug=body.plan)
    db.commit()
    return {"user": user}


@router.get("/admin/models")
def admin_models(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"models": service.list_models(db)}


@router.post("/admin/models", status_code=201)
def admin_create_model(body: ModelIn, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    model = service.create_model(
        db,
        model_id=body.id,
        label=body.label,
        max_output_tokens=body.max_output_tokens,
        sort_order=body.sort_order,
        enabled=body.enabled,
    )
    db.commit()
    return {"model": model}


@router.patch("/admin/models/{model_id}")
def admin_update_model(model_id: str, body: ModelPatch, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    model = service.update_model(
        db,
        model_id,
        label=body.label,
        max_output_tokens=body.max_output_tokens,
        sort_order=body.sort_order,
        enabled=body.enabled,
    )
    db.commit()
    return {"model": model}


@router.get("/admin/models/{model_id}/prices")
def admin_prices(model_id: str, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"prices": service.list_prices(db, model_id)}


@router.post("/admin/models/{model_id}/prices", status_code=201)
def admin_add_price(model_id: str, body: PriceIn, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    price = service.add_price(
        db,
        model_id,
        input_per_1k=body.input_per_1k,
        output_per_1k=body.output_per_1k,
        effective_from=body.effective_from,
    )
    db.commit()
    return {"price": price}


@router.get("/admin/channels")
def admin_channels(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"channels": service.list_channels(db)}


@router.post("/admin/channels", status_code=201)
def admin_create_channel(body: ChannelIn, _user: CurrentAdmin, config: CurrentConfig, db: DbSession) -> dict[str, object]:
    channel = service.create_channel(
        db,
        config,
        model_id=body.model_id,
        base_url=body.base_url,
        upstream_model=body.upstream_model,
        api_key=body.api_key,
        priority=body.priority,
        note=body.note,
    )
    db.commit()
    return {"channel": channel}


@router.patch("/admin/channels/{channel_id}")
def admin_update_channel(
    channel_id: str,
    body: ChannelPatch,
    _user: CurrentAdmin,
    config: CurrentConfig,
    db: DbSession,
) -> dict[str, object]:
    channel = service.update_channel(
        db,
        config,
        channel_id,
        upstream_model=body.upstream_model,
        priority=body.priority,
        note=body.note,
        enabled=body.enabled,
        api_key=body.api_key,
    )
    db.commit()
    return {"channel": channel}


@router.get("/admin/plans")
def admin_plans(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"plans": service.list_plans(db)}


@router.post("/admin/plans", status_code=201)
def admin_create_plan(body: PlanIn, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    plan = service.create_plan(
        db,
        slug=body.slug,
        name=body.name,
        period=body.period,
        monthly_credits=body.monthly_credits,
        credit_ttl_days=body.credit_ttl_days,
        on_sale=body.on_sale,
        price_cents=body.price_cents,
    )
    db.commit()
    return {"plan": plan}


@router.patch("/admin/plans/{slug}")
def admin_update_plan(slug: str, body: PlanPatch, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    plan = service.update_plan(
        db,
        slug,
        name=body.name,
        period=body.period,
        monthly_credits=body.monthly_credits,
        credit_ttl_days=body.credit_ttl_days,
        on_sale=body.on_sale,
        price_cents=body.price_cents,
    )
    db.commit()
    return {"plan": plan}
