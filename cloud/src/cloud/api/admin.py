"""MosaelCloud 管理端 API。

**只接受浏览器会话 + `role=admin`**。设备令牌不能管理部署。
响应全部显式组装,不含密码哈希、设备令牌或上游 Key。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from cloud.admin import service
from cloud.admin.schemas import (
    AdjustIn,
    BanIn,
    ChannelIn,
    IpBanIn,
    ChannelPatch,
    GiftIn,
    ModelIn,
    ModelPatch,
    PlanIn,
    PlanPatch,
    PriceIn,
    OrderRefundIn,
    ProviderIn,
    UserPatch,
    ProviderPatch,
    RoleIn,
    SubscribeIn,
)
from cloud.api.deps import CurrentAdmin, CurrentConfig, DbSession
from cloud.domain import audit
from cloud.models import now

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


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: str, body: UserPatch, actor: CurrentAdmin, db: DbSession
) -> dict[str, object]:
    user = service.update_user(db, user_id, display_name=body.display_name, handle=body.handle)
    audit.record(db, actor=actor, action="user.update", target_type="user", target_id=user_id,
                 detail={"display_name": body.display_name, "handle": body.handle})
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/ban")
def admin_ban_user(user_id: str, body: BanIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.set_ban(db, user_id, banned=True, reason=body.reason, acting_user_id=actor.id)
    audit.record(db, actor=actor, action="user.ban", target_type="user", target_id=user_id,
                 detail={"reason": body.reason})
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/unban")
def admin_unban_user(user_id: str, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.set_ban(db, user_id, banned=False, reason="", acting_user_id=actor.id)
    audit.record(db, actor=actor, action="user.unban", target_type="user", target_id=user_id)
    db.commit()
    return {"user": user}


@router.delete("/admin/users/{user_id}", status_code=204)
def admin_delete_user(user_id: str, request: Request, actor: CurrentAdmin, db: DbSession) -> Response:
    from sqlalchemy import select

    from cloud.models import CloudMediaArtifact, CloudMediaUpload

    keys = list(db.scalars(select(CloudMediaArtifact.storage_key).where(CloudMediaArtifact.user_id == user_id))) + list(
        db.scalars(select(CloudMediaUpload.storage_key).where(CloudMediaUpload.user_id == user_id))
    )
    service.delete_user(db, user_id, acting_user_id=actor.id)
    audit.record(db, actor=actor, action="user.delete", target_type="user", target_id=user_id)
    db.commit()
    for key in keys:
        try:
            request.app.state.artifact_storage.delete(key)
        except Exception:  # noqa: BLE001 —— DB 已删；对象清理失败由生命周期兜底
            pass
    return Response(status_code=204)


@router.post("/admin/users/{user_id}/role")
def admin_user_role(user_id: str, body: RoleIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.set_role(db, user_id, body.role)
    audit.record(db, actor=actor, action="user.role", target_type="user", target_id=user_id, detail={"role": body.role})
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/credits")
def admin_user_credits(user_id: str, body: GiftIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.gift(db, user_id, amount=body.credits, days=body.days, note=body.note)
    audit.record(db, actor=actor, action="user.credits", target_type="user", target_id=user_id,
                 detail={"credits": body.credits, "days": body.days, "note": body.note})
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/credits/adjust")
def admin_adjust_user_credits(
    user_id: str, body: AdjustIn, actor: CurrentAdmin, db: DbSession
) -> dict[str, object]:
    user = service.adjust_credits(db, user_id, delta=body.delta, days=body.days, note=body.note)
    audit.record(db, actor=actor, action="user.credits_adjust", target_type="user", target_id=user_id,
                 detail={"delta": body.delta, "days": body.days, "note": body.note})
    db.commit()
    return {"user": user}


@router.post("/admin/users/{user_id}/reset-password")
def admin_reset_user_password(user_id: str, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    temporary = service.reset_password(db, user_id, acting_user_id=actor.id)
    audit.record(db, actor=actor, action="user.password_reset", target_type="user", target_id=user_id)
    db.commit()
    return {"temporary_password": temporary}


@router.delete("/admin/users/{user_id}/subscriptions", status_code=204)
def admin_cancel_user_subscription(user_id: str, actor: CurrentAdmin, db: DbSession) -> Response:
    service.cancel_subscription(db, user_id)
    audit.record(db, actor=actor, action="user.cancel_subscription", target_type="user", target_id=user_id)
    db.commit()
    return Response(status_code=204)


@router.post("/admin/users/{user_id}/subscriptions")
def admin_user_subscription(user_id: str, body: SubscribeIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    user = service.subscribe(db, user_id, plan_slug=body.plan)
    audit.record(db, actor=actor, action="user.subscribe", target_type="user", target_id=user_id,
                 detail={"plan": body.plan})
    db.commit()
    return {"user": user}


@router.get("/admin/ip-bans")
def admin_ip_bans(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"bans": service.list_ip_bans(db)}


@router.post("/admin/ip-bans", status_code=201)
def admin_ban_ip(body: IpBanIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    ban = service.ban_ip(db, ip=body.ip, reason=body.reason)
    audit.record(db, actor=actor, action="ip.ban", target_type="ip", target_id=ban["ip"],
                 detail={"reason": body.reason})
    db.commit()
    return {"ban": ban}


@router.delete("/admin/ip-bans/{ip}", status_code=204)
def admin_unban_ip(ip: str, actor: CurrentAdmin, db: DbSession) -> Response:
    service.unban_ip(db, ip)
    audit.record(db, actor=actor, action="ip.unban", target_type="ip", target_id=ip)
    db.commit()
    return Response(status_code=204)


@router.get("/admin/orders")
def admin_orders(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"orders": service.list_orders(db)}


@router.get("/admin/usage")
def admin_usage(_user: CurrentAdmin, db: DbSession, days: int = Query(default=7, ge=1, le=90)) -> dict[str, object]:
    return service.usage_summary(db, days=days)


@router.get("/admin/audit")
def admin_audit(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"events": service.list_audit(db)}


@router.post("/admin/orders/{order_id}/refund")
def admin_refund_order(
    order_id: str, body: OrderRefundIn, actor: CurrentAdmin, db: DbSession
) -> dict[str, object]:
    order = service.mark_order_refunded(db, order_id, amount_cents=body.amount_cents, note=body.note, at=now())
    audit.record(db, actor=actor, action="order.refund", target_type="order", target_id=order_id,
                 detail={"amount_cents": order.refund_cents, "note": order.refund_note})
    db.commit()
    return {"order": {"id": order.id, "refunded_at": order.refunded_at.isoformat(),
                      "refund_cents": order.refund_cents, "note": order.refund_note}}


@router.get("/admin/models")
def admin_models(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"models": service.list_models(db)}


@router.post("/admin/models", status_code=201)
def admin_create_model(body: ModelIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    model = service.create_model(
        db,
        label=body.label,
        interaction=body.interaction,
        capability=body.capability,
        max_output_tokens=body.max_output_tokens,
        sort_order=body.sort_order,
        enabled=body.enabled,
    )
    audit.record(db, actor=actor, action="model.create", target_type="model", target_id=model["id"],
                 detail={"label": body.label, "interaction": body.interaction})
    db.commit()
    return {"model": model}


@router.patch("/admin/models/{model_id}")
def admin_update_model(model_id: str, body: ModelPatch, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    model = service.update_model(
        db,
        model_id,
        label=body.label,
        interaction=body.interaction,
        capability=body.capability,
        max_output_tokens=body.max_output_tokens,
        sort_order=body.sort_order,
        enabled=body.enabled,
    )
    audit.record(db, actor=actor, action="model.update", target_type="model", target_id=model_id,
                 detail={"label": body.label, "max_output_tokens": body.max_output_tokens, "enabled": body.enabled})
    db.commit()
    return {"model": model}


@router.get("/admin/models/{model_id}/prices")
def admin_prices(model_id: str, _user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"prices": service.list_prices(db, model_id)}


@router.post("/admin/models/{model_id}/prices", status_code=201)
def admin_add_price(model_id: str, body: PriceIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    price = service.add_price(
        db,
        model_id,
        components=body.components,
        effective_from=body.effective_from,
    )
    audit.record(db, actor=actor, action="model.price", target_type="model", target_id=model_id,
                 detail={"components": body.components})
    db.commit()
    return {"price": price}


@router.get("/admin/providers")
def admin_providers(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"providers": service.list_providers(db)}


@router.post("/admin/providers", status_code=201)
def admin_create_provider(body: ProviderIn, actor: CurrentAdmin, config: CurrentConfig, db: DbSession) -> dict[str, object]:
    provider = service.create_provider(
        db, config, name=body.name, base_url=body.base_url, api_key=body.api_key, note=body.note,
        adapter=body.adapter, adapter_config=body.config,
    )
    audit.record(db, actor=actor, action="provider.create", target_type="provider", target_id=provider["id"],
                 detail={"name": body.name, "base_url": body.base_url, "api_key_set": True})
    db.commit()
    return {"provider": provider}


@router.patch("/admin/providers/{provider_id}")
def admin_update_provider(
    provider_id: str, body: ProviderPatch, actor: CurrentAdmin, config: CurrentConfig, db: DbSession
) -> dict[str, object]:
    provider = service.update_provider(
        db, config, provider_id, name=body.name, adapter=body.adapter, note=body.note,
        enabled=body.enabled, api_key=body.api_key, adapter_config=body.config
    )
    audit.record(db, actor=actor, action="provider.update", target_type="provider", target_id=provider_id,
                 detail={"enabled": body.enabled, "api_key_replaced": bool(body.api_key)})
    db.commit()
    return {"provider": provider}


@router.get("/admin/channels")
def admin_channels(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"channels": service.list_channels(db)}


@router.post("/admin/channels", status_code=201)
def admin_create_channel(body: ChannelIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
    channel = service.create_channel(
        db,
        model_id=body.model_id,
        provider_id=body.provider_id,
        upstream_model=body.upstream_model,
        priority=body.priority,
        note=body.note,
    )
    audit.record(db, actor=actor, action="channel.create", target_type="channel", target_id=channel["id"],
                 detail={"model_id": body.model_id, "provider_id": body.provider_id})
    db.commit()
    return {"channel": channel}


@router.patch("/admin/channels/{channel_id}")
def admin_update_channel(
    channel_id: str,
    body: ChannelPatch,
    actor: CurrentAdmin,
    db: DbSession,
) -> dict[str, object]:
    channel = service.update_channel(
        db,
        channel_id,
        upstream_model=body.upstream_model,
        priority=body.priority,
        note=body.note,
        enabled=body.enabled,
    )
    audit.record(db, actor=actor, action="channel.update", target_type="channel", target_id=channel_id,
                 detail={"enabled": body.enabled})
    db.commit()
    return {"channel": channel}


@router.post("/admin/channels/{channel_id}/test")
def admin_test_channel(
    channel_id: str, actor: CurrentAdmin, request: Request, config: CurrentConfig, db: DbSession
) -> dict[str, object]:
    result = service.test_channel(
        db, config, channel_id, transport=request.app.state.upstream_transport
    )
    audit.record(
        db,
        actor=actor,
        action="channel.test",
        target_type="channel",
        target_id=channel_id,
        detail={"ok": result["ok"], "status": result["status"]},
    )
    db.commit()
    return {"result": result}


@router.get("/admin/plans")
def admin_plans(_user: CurrentAdmin, db: DbSession) -> dict[str, object]:
    return {"plans": service.list_plans(db)}


@router.post("/admin/plans", status_code=201)
def admin_create_plan(body: PlanIn, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
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
    audit.record(db, actor=actor, action="plan.create", target_type="plan", target_id=body.slug,
                 detail={"name": body.name, "monthly_credits": body.monthly_credits})
    db.commit()
    return {"plan": plan}


@router.delete("/admin/plans/{slug}", status_code=204)
def admin_delete_plan(slug: str, actor: CurrentAdmin, db: DbSession) -> Response:
    service.delete_plan(db, slug)
    audit.record(db, actor=actor, action="plan.delete", target_type="plan", target_id=slug)
    db.commit()
    return Response(status_code=204)


@router.patch("/admin/plans/{slug}")
def admin_update_plan(slug: str, body: PlanPatch, actor: CurrentAdmin, db: DbSession) -> dict[str, object]:
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
    audit.record(db, actor=actor, action="plan.update", target_type="plan", target_id=slug,
                 detail={"name": body.name, "on_sale": body.on_sale})
    db.commit()
    return {"plan": plan}
