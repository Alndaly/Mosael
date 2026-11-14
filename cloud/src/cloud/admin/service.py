"""管理端读模型与写动作。响应只包含显式白名单字段,绝不带密码哈希或上游 Key。"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx2

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.domain import catalog, credits
from cloud.domain.identity import set_identity
from cloud.domain import admin as role_admin
from cloud.domain import orders as order_domain
from cloud.domain.channel_keys import unseal
from cloud.gateway import upstream
from cloud.errors import CloudError
from cloud.security import hash_password, new_token
from cloud.models import (
    CloudAdminAudit,
    CloudDeviceToken,
    CloudGatewayCall,
    CloudGatewayModel,
    CloudIpBan,
    CloudModelPrice,
    CloudOrder,
    CloudSession,
    CloudPlan,
    CloudSubscription,
    CloudUpstreamChannel,
    CloudUpstreamProvider,
    CloudUser,
    new_id,
    now,
)


def overview(db: Session) -> dict[str, int]:
    def count(statement) -> int:
        return int(db.scalar(statement) or 0)

    return {
        "users": count(select(func.count()).select_from(CloudUser)),
        "admins": count(select(func.count()).select_from(CloudUser).where(CloudUser.role == role_admin.ROLE_ADMIN)),
        "subscriptions": count(
            select(func.count()).select_from(CloudSubscription).where(CloudSubscription.status == "active")
        ),
        "models": count(select(func.count()).select_from(CloudGatewayModel)),
        "providers": count(select(func.count()).select_from(CloudUpstreamProvider)),
        "channels": count(select(func.count()).select_from(CloudUpstreamChannel)),
        "orders": count(select(func.count()).select_from(CloudOrder)),
    }


def _user_view(db: Session, user: CloudUser, at: datetime) -> dict[str, object]:
    balance = credits.balance(db, user.id, at=at)
    subscription = db.scalars(
        select(CloudSubscription)
        .where(CloudSubscription.user_id == user.id, CloudSubscription.status == "active")
        .order_by(CloudSubscription.started_at.desc())
    ).first()
    plan = db.get(CloudPlan, subscription.plan_id) if subscription else None
    return {
        "id": user.id,
        "email": user.email,
        "phone": user.phone,
        "handle": user.handle,
        "display_name": user.display_name,
        "role": user.role,
        "official": user.official,
        "banned": user.banned_at is not None,
        "ban_reason": user.ban_reason,
        "has_password": bool(user.password_hash),
        "mfa_enabled": bool(user.mfa_enabled_at and user.mfa_totp_secret_encrypted),
        "created_at": user.created_at.isoformat(),
        "credits": balance.total,
        "subscription": {
            "plan": plan.slug if plan else None,
            "name": plan.name if plan else None,
            "ends_at": subscription.ends_at.isoformat() if subscription else None,
            "next_grant_at": subscription.next_grant_at.isoformat() if subscription else None,
        }
        if subscription and plan
        else None,
    }


def list_users(db: Session, *, query: str = "") -> list[dict[str, object]]:
    statement = select(CloudUser).order_by(CloudUser.created_at.desc()).limit(100)
    term = query.strip().lower()
    if term:
        like = f"%{term}%"
        statement = statement.where(
            or_(
                func.lower(func.coalesce(CloudUser.email, "")).like(like),
                func.lower(func.coalesce(CloudUser.phone, "")).like(like),
                func.lower(func.coalesce(CloudUser.display_name, "")).like(like),
                func.lower(func.coalesce(CloudUser.handle, "")).like(like),
            )
        )
    at = now()
    return [_user_view(db, user, at) for user in db.scalars(statement).all()]


def user_detail(db: Session, user_id: str) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    at = now()
    view = _user_view(db, user, at)
    balance = credits.balance(db, user.id, at=at)
    view["credit_batches"] = [
        {"remaining": one.remaining, "source": one.source, "expires_at": one.expires_at.isoformat()}
        for one in balance.batches
    ]
    view["subscriptions"] = [
        {
            "id": one.id,
            "plan": (db.get(CloudPlan, one.plan_id).slug if db.get(CloudPlan, one.plan_id) else None),
            "status": one.status,
            "started_at": one.started_at.isoformat(),
            "ends_at": one.ends_at.isoformat(),
        }
        for one in db.scalars(
            select(CloudSubscription)
            .where(CloudSubscription.user_id == user.id)
            .order_by(CloudSubscription.started_at.desc())
        ).all()
    ]
    view["orders"] = [
        order_domain.order_view(db, one)
        for one in db.scalars(
            select(CloudOrder).where(CloudOrder.user_id == user.id).order_by(CloudOrder.created_at.desc()).limit(20)
        ).all()
    ]
    return view


def set_role(db: Session, user_id: str, role: str) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    if role == role_admin.ROLE_ADMIN:
        role_admin.grant(db, user)
    else:
        try:
            role_admin.revoke(db, user)
        except role_admin.RoleError as exc:
            raise CloudError(409, "last_admin") from exc
    return _user_view(db, user, now())


def update_user(
    db: Session, user_id: str, *, display_name: str | None, handle: str | None
) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    user = set_identity(db, user, display_name=display_name, handle=handle)
    return _user_view(db, user, now())


def set_ban(
    db: Session, user_id: str, *, banned: bool, reason: str, acting_user_id: str
) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    if banned:
        if user.id == acting_user_id:
            raise CloudError(400, "cannot_ban_self")
        if user.official:
            raise CloudError(409, "cannot_ban_official")
        if user.role == role_admin.ROLE_ADMIN:
            admins = int(db.scalar(
                select(func.count()).select_from(CloudUser).where(
                    CloudUser.role == role_admin.ROLE_ADMIN,
                    CloudUser.banned_at.is_(None),
                )
            ) or 0)
            if admins <= 1:
                raise CloudError(409, "last_admin")
        user.banned_at = now()
        user.ban_reason = reason.strip()[:200]
        # 封禁立即生效:已有浏览器会话和桌面设备令牌都撤掉。
        db.execute(delete(CloudSession).where(CloudSession.user_id == user.id))
        db.execute(delete(CloudDeviceToken).where(CloudDeviceToken.user_id == user.id))
    else:
        user.banned_at = None
        user.ban_reason = ""
    db.flush()
    return _user_view(db, user, now())


def delete_user(db: Session, user_id: str, *, acting_user_id: str) -> None:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    if user.id == acting_user_id:
        raise CloudError(400, "cannot_delete_self")
    if user.official:
        raise CloudError(409, "official_account")
    if user.role == role_admin.ROLE_ADMIN:
        admins = int(db.scalar(
            select(func.count()).select_from(CloudUser).where(CloudUser.role == role_admin.ROLE_ADMIN)
        ) or 0)
        if admins <= 1:
            raise CloudError(409, "last_admin")
    db.delete(user)
    db.flush()


def gift(db: Session, user_id: str, *, amount: int, days: int, note: str) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    credits.gift(db, user, amount=amount, days=days, note=note, at=now())
    return _user_view(db, user, now())


def adjust_credits(
    db: Session, user_id: str, *, delta: int, days: int, note: str
) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    credits.adjust(db, user, delta=delta, days=days, note=note, at=now())
    return _user_view(db, user, now())


def cancel_subscription(db: Session, user_id: str) -> dict[str, object]:
    """结束用户的当前套餐订阅。已发的积分不追回,只是不再发下一批。"""
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    at = now()
    active = db.scalars(
        select(CloudSubscription).where(
            CloudSubscription.user_id == user.id,
            CloudSubscription.status == "active",
        )
    ).all()
    if not active:
        raise CloudError(409, "no_subscription")
    for subscription in active:
        subscription.status = "ended"
        subscription.ends_at = min(subscription.ends_at, at)
    db.flush()
    return _user_view(db, user, at)


def subscribe(db: Session, user_id: str, *, plan_slug: str) -> dict[str, object]:
    user = db.get(CloudUser, user_id)
    plan = db.scalar(select(CloudPlan).where(CloudPlan.slug == plan_slug, CloudPlan.deleted_at.is_(None)))
    if user is None:
        raise CloudError(404, "user_not_found")
    if plan is None:
        raise CloudError(404, "plan_not_found")
    credits.subscribe(db, user, plan, at=now())
    return _user_view(db, user, now())


def reset_password(db: Session, user_id: str, *, acting_user_id: str) -> str:
    user = db.get(CloudUser, user_id)
    if user is None:
        raise CloudError(404, "user_not_found")
    if user.id == acting_user_id:
        raise CloudError(400, "cannot_reset_self")
    temporary = new_token(12)
    user.password_hash = hash_password(temporary)
    #: 密码变了,旧会话和桌面令牌都必须失效;管理员把临时密码交给本人后由本人改密码。
    db.execute(delete(CloudSession).where(CloudSession.user_id == user.id))
    db.execute(delete(CloudDeviceToken).where(CloudDeviceToken.user_id == user.id))
    db.flush()
    return temporary


def _model_labels(db: Session) -> dict[str, str]:
    return catalog.display_labels(db.scalars(select(CloudGatewayModel)).all())


def _model_view(db: Session, model: CloudGatewayModel, at: datetime, display_label: str) -> dict[str, object]:
    price = catalog.current_price(db, model.id, at=at)
    channels = db.execute(
        select(CloudUpstreamChannel, CloudUpstreamProvider)
        .join(CloudUpstreamProvider, CloudUpstreamProvider.id == CloudUpstreamChannel.provider_id)
        .where(CloudUpstreamChannel.model_id == model.id)
    ).all()
    active = [one for one in channels if one[0].enabled and one[1].enabled]
    reasons = []
    if not model.enabled:
        reasons.append("disabled")
    if price is None:
        reasons.append("missing_price")
    if not active:
        reasons.append("missing_channel")
    return {
        "id": model.id,
        "label": model.label,
        "display_label": display_label,
        "interaction": model.interaction,
        "capability": model.capability,
        "max_output_tokens": catalog.max_output_tokens(model),
        "enabled": model.enabled,
        "sort_order": model.sort_order,
        "current_price": (
            {
                "components": catalog.price_components(db, price.id),
                "effective_from": price.effective_from.isoformat(),
            }
            if price
            else None
        ),
        "channel_count": len(channels),
        "active_channel_count": len(active),
        "listed": not reasons,
        "not_listed_reasons": reasons,
    }


def list_models(db: Session) -> list[dict[str, object]]:
    at = now()
    labels = _model_labels(db)
    return [
        _model_view(db, one, at, labels[one.id])
        for one in db.scalars(
            select(CloudGatewayModel).order_by(
                CloudGatewayModel.sort_order, CloudGatewayModel.label, CloudGatewayModel.created_at, CloudGatewayModel.id
            )
        ).all()
    ]


def _model_capability(interaction: str, capability: dict[str, object], max_output_tokens: int | None) -> dict[str, object]:
    if interaction == "stream":
        if not max_output_tokens:
            raise CloudError(422, "gateway_capability_invalid")
        return {**capability, "max_output_tokens": max_output_tokens}
    if interaction == "job":
        if not isinstance(capability.get("reservation"), dict) or not capability["reservation"]:
            raise CloudError(422, "gateway_capability_invalid")
        return dict(capability)
    raise CloudError(422, "gateway_capability_invalid")


def create_model(db: Session, *, label: str, interaction: str, capability: dict[str, object], max_output_tokens: int | None, sort_order: int, enabled: bool) -> dict[str, object]:
    resolved = _model_capability(interaction, capability, max_output_tokens)
    model = catalog.upsert_model(
        db,
        model_id=new_id(),
        label=label,
        interaction=interaction,
        capability=resolved,
        enabled=enabled,
        sort_order=sort_order,
    )
    labels = _model_labels(db)
    return _model_view(db, model, now(), labels[model.id])


def update_model(db: Session, model_id: str, *, label: str, interaction: str, capability: dict[str, object], max_output_tokens: int | None, sort_order: int, enabled: bool) -> dict[str, object]:
    model = db.get(CloudGatewayModel, model_id)
    if model is None:
        raise CloudError(404, "model_not_found")
    resolved = _model_capability(interaction, capability, max_output_tokens)
    catalog.upsert_model(
        db,
        model_id=model_id,
        label=label,
        interaction=interaction,
        capability=resolved,
        enabled=enabled,
        sort_order=sort_order,
    )
    labels = _model_labels(db)
    return _model_view(db, model, now(), labels[model.id])


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def add_price(db: Session, model_id: str, *, components: dict[str, int], effective_from: datetime | None) -> dict[str, object]:
    if db.get(CloudGatewayModel, model_id) is None:
        raise CloudError(404, "model_not_found")
    if not components or any(value < 0 for value in components.values()):
        raise CloudError(422, "gateway_capability_invalid")
    price = catalog.add_price_components(
        db,
        model_id=model_id,
        components={unit: int(value) for unit, value in components.items()},
        effective_from=_utc_naive(effective_from) if effective_from else now(),
    )
    return {
        "components": catalog.price_components(db, price.id),
        "effective_from": price.effective_from.isoformat(),
    }


def list_prices(db: Session, model_id: str) -> list[dict[str, object]]:
    if db.get(CloudGatewayModel, model_id) is None:
        raise CloudError(404, "model_not_found")
    return [
        {
            "components": catalog.price_components(db, one.id),
            "effective_from": one.effective_from.isoformat(),
        }
        for one in db.scalars(
            select(CloudModelPrice)
            .where(CloudModelPrice.model_id == model_id)
            .order_by(CloudModelPrice.effective_from.desc())
        ).all()
    ]


def _provider_view(provider: CloudUpstreamProvider) -> dict[str, object]:
    return {
        "id": provider.id,
        "name": provider.name,
        "adapter": provider.adapter,
        "config": provider.config,
        "base_url": provider.base_url,
        "enabled": provider.enabled,
        "note": provider.note,
        "has_api_key": bool(provider.api_key_encrypted),
    }


def list_providers(db: Session) -> list[dict[str, object]]:
    return [
        _provider_view(one)
        for one in db.scalars(
            select(CloudUpstreamProvider).order_by(CloudUpstreamProvider.name, CloudUpstreamProvider.id)
        ).all()
    ]


def _validate_adapter_config(adapter: str, adapter_config: dict[str, object] | None) -> None:
    if adapter != "comfyui":
        return
    workflows = (adapter_config or {}).get("workflows")
    if not isinstance(workflows, dict) or not workflows:
        raise CloudError(422, "provider_config_invalid")
    for name, workflow in workflows.items():
        if not isinstance(name, str) or not name or not isinstance(workflow, dict):
            raise CloudError(422, "provider_config_invalid")
        bindings = workflow.get("bindings")
        if not isinstance(workflow.get("prompt"), dict) or not isinstance(bindings, dict) or "prompt" not in bindings:
            raise CloudError(422, "provider_config_invalid")


def create_provider(
    db: Session, config: CloudConfig, *, name: str, base_url: str, api_key: str, note: str,
    adapter: str = "openai", adapter_config: dict[str, object] | None = None
) -> dict[str, object]:
    _validate_adapter_config(adapter, adapter_config)
    if not base_url.startswith(("https://", "http://")):
        raise CloudError(400, "channel_url_invalid")
    if not config.channel_key:
        raise CloudError(503, "gateway_not_configured")
    provider = catalog.add_provider(
        db, config, name=name, base_url=base_url, api_key=api_key, note=note, adapter=adapter,
        adapter_config=adapter_config,
    )
    return _provider_view(provider)


def update_provider(
    db: Session, config: CloudConfig, provider_id: str, *, name: str, adapter: str, note: str,
    enabled: bool, api_key: str, adapter_config: dict[str, object] | None = None
) -> dict[str, object]:
    provider = db.get(CloudUpstreamProvider, provider_id)
    if provider is None:
        raise CloudError(404, "provider_not_found")
    _validate_adapter_config(adapter, adapter_config)
    provider.name = name
    provider.adapter = adapter
    provider.config = dict(adapter_config or {})
    provider.note = note
    provider.enabled = enabled
    if api_key:
        if not config.channel_key:
            raise CloudError(503, "gateway_not_configured")
        catalog.replace_provider_key(db, config, provider, api_key)
    db.flush()
    return _provider_view(provider)


def list_ip_bans(db: Session) -> list[dict[str, object]]:
    return [
        {"ip": one.ip, "reason": one.reason, "created_at": one.created_at.isoformat()}
        for one in db.scalars(select(CloudIpBan).order_by(CloudIpBan.created_at.desc())).all()
    ]


def ban_ip(db: Session, *, ip: str, reason: str) -> dict[str, object]:
    import ipaddress

    try:
        canonical = str(ipaddress.ip_address(ip.strip()))
    except ValueError as exc:
        raise CloudError(400, "invalid_ip") from exc
    row = db.get(CloudIpBan, canonical)
    if row is None:
        row = CloudIpBan(ip=canonical, reason=reason.strip()[:200], created_at=now())
        db.add(row)
    else:
        row.reason = reason.strip()[:200]
    db.flush()
    return {"ip": row.ip, "reason": row.reason, "created_at": row.created_at.isoformat()}


def unban_ip(db: Session, ip: str) -> None:
    row = db.get(CloudIpBan, ip)
    if row is not None:
        db.delete(row)
        db.flush()


def delete_plan(db: Session, slug: str) -> None:
    """软删除:历史订阅 / 订单还引用这一行。已订阅的人照常用完已发积分,但不再能新买或新开通。"""
    plan = db.scalar(select(CloudPlan).where(CloudPlan.slug == slug, CloudPlan.deleted_at.is_(None)))
    if plan is None:
        raise CloudError(404, "plan_not_found")
    plan.deleted_at = now()
    plan.on_sale = False
    db.flush()


def _channel_view(
    channel: CloudUpstreamChannel, provider: CloudUpstreamProvider, model_label: str
) -> dict[str, object]:
    return {
        "id": channel.id,
        "model_id": channel.model_id,
        "model_label": model_label,
        "provider_id": channel.provider_id,
        "provider_name": provider.name,
        "base_url": provider.base_url,
        "upstream_model": channel.upstream_model,
        "priority": channel.priority,
        "enabled": channel.enabled,
        "cooldown_until": channel.cooldown_until.isoformat() if channel.cooldown_until else None,
        "note": channel.note,
        "has_api_key": bool(provider.api_key_encrypted),
    }


def list_channels(db: Session) -> list[dict[str, object]]:
    labels = _model_labels(db)
    return [
        _channel_view(channel, provider, labels.get(channel.model_id, channel.model_id))
        for channel, provider in db.execute(
            select(CloudUpstreamChannel, CloudUpstreamProvider)
            .join(CloudUpstreamProvider, CloudUpstreamProvider.id == CloudUpstreamChannel.provider_id)
            .order_by(CloudUpstreamChannel.model_id, CloudUpstreamChannel.priority)
        ).all()
    ]


def create_channel(db: Session, *, model_id: str, provider_id: str, upstream_model: str, priority: int, note: str) -> dict[str, object]:
    if db.get(CloudGatewayModel, model_id) is None:
        raise CloudError(404, "model_not_found")
    provider = db.get(CloudUpstreamProvider, provider_id)
    if provider is None:
        raise CloudError(404, "provider_not_found")
    channel = catalog.add_channel(
        db,
        model_id=model_id,
        provider_id=provider_id,
        upstream_model=upstream_model,
        priority=priority,
        note=note,
    )
    labels = _model_labels(db)
    return _channel_view(channel, provider, labels[model_id])


def update_channel(db: Session, channel_id: str, *, upstream_model: str, priority: int, note: str, enabled: bool) -> dict[str, object]:
    channel = db.get(CloudUpstreamChannel, channel_id)
    if channel is None:
        raise CloudError(404, "channel_not_found")
    provider = db.get(CloudUpstreamProvider, channel.provider_id)
    if provider is None:
        raise CloudError(404, "provider_not_found")
    channel.upstream_model = upstream_model
    channel.priority = priority
    channel.note = note
    channel.enabled = enabled
    db.flush()
    labels = _model_labels(db)
    return _channel_view(channel, provider, labels.get(channel.model_id, channel.model_id))


def _plan_view(plan: CloudPlan) -> dict[str, object]:
    return {
        "slug": plan.slug,
        "name": plan.name,
        "period": plan.period,
        "monthly_credits": plan.monthly_credits,
        "credit_ttl_days": plan.credit_ttl_days,
        "on_sale": plan.on_sale,
        "price_cents": plan.price_cents,
        "currency": plan.currency,
    }


def list_plans(db: Session) -> list[dict[str, object]]:
    return [
        _plan_view(one)
        for one in db.scalars(select(CloudPlan).where(CloudPlan.deleted_at.is_(None)).order_by(CloudPlan.slug)).all()
    ]


def create_plan(db: Session, *, slug: str, name: str, period: str, monthly_credits: int, credit_ttl_days: int, on_sale: bool, price_cents: int | None) -> dict[str, object]:
    if db.scalar(select(CloudPlan).where(CloudPlan.slug == slug)) is not None:
        raise CloudError(409, "plan_exists")
    plan = CloudPlan(
        slug=slug,
        name=name,
        period=period,
        monthly_credits=monthly_credits,
        credit_ttl_days=credit_ttl_days,
        on_sale=on_sale,
        price_cents=price_cents,
    )
    db.add(plan)
    db.flush()
    return _plan_view(plan)


def update_plan(db: Session, slug: str, *, name: str, period: str, monthly_credits: int, credit_ttl_days: int, on_sale: bool, price_cents: int | None) -> dict[str, object]:
    plan = db.scalar(select(CloudPlan).where(CloudPlan.slug == slug, CloudPlan.deleted_at.is_(None)))
    if plan is None:
        raise CloudError(404, "plan_not_found")
    plan.name = name
    plan.period = period
    plan.monthly_credits = monthly_credits
    plan.credit_ttl_days = credit_ttl_days
    plan.on_sale = on_sale
    plan.price_cents = price_cents
    db.flush()
    return _plan_view(plan)


def list_audit(db: Session, *, limit: int = 100) -> list[dict[str, object]]:
    return [
        {
            "id": one.id,
            "actor_email": one.actor_email,
            "action": one.action,
            "target_type": one.target_type,
            "target_id": one.target_id,
            "detail": one.detail,
            "created_at": one.created_at.isoformat(),
        }
        for one in db.scalars(
            select(CloudAdminAudit).order_by(CloudAdminAudit.created_at.desc()).limit(limit)
        ).all()
    ]


def test_channel(
    db: Session,
    config: CloudConfig,
    channel_id: str,
    *,
    transport: httpx2.BaseTransport | None = None,
) -> dict[str, object]:
    """发一次最小对话请求验证上游。只回状态 / 延迟 / 用量,不回 Key。"""
    channel = db.get(CloudUpstreamChannel, channel_id)
    if channel is None:
        raise CloudError(404, "channel_not_found")
    provider = db.get(CloudUpstreamProvider, channel.provider_id)
    if provider is None:
        raise CloudError(404, "provider_not_found")
    started = time.monotonic()
    body = {
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        with upstream.new_client(transport) as client:
            response = upstream.open_chat(
                client,
                provider,
                upstream_model=channel.upstream_model,
                api_key=unseal(config, provider.api_key_encrypted),
                body=body,
            )
            try:
                raw = response.read()
            finally:
                response.close()
    except upstream.UpstreamFailure as failure:
        return {
            "ok": False,
            "status": failure.status,
            "detail": failure.detail,
            "retryable": failure.retryable,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    latency = int((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    usage = upstream.usage_of(payload)
    return {
        "ok": True,
        "status": 200,
        "latency_ms": latency,
        "upstream_model": channel.upstream_model,
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
    }


def list_orders(db: Session, *, limit: int = 100) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for order in db.scalars(
        select(CloudOrder).order_by(CloudOrder.created_at.desc()).limit(limit)
    ).all():
        view = order_domain.order_view(db, order)
        user = db.get(CloudUser, order.user_id) if order.user_id else None
        view["user"] = {"email": user.email, "handle": user.handle} if user else None
        events.append(view)
    return events


def usage_summary(db: Session, *, days: int = 7) -> dict[str, object]:
    days = max(1, min(days, 90))
    since = now() - timedelta(days=days)
    calls = db.scalars(
        select(CloudGatewayCall)
        .where(CloudGatewayCall.created_at >= since)
        .order_by(CloudGatewayCall.created_at.desc())
        .limit(5000)
    ).all()
    totals = {"calls": 0, "charged": 0, "input_tokens": 0, "output_tokens": 0}
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "charged": 0})
    by_model: dict[str, dict[str, int]] = defaultdict(lambda: {"calls": 0, "charged": 0})
    for call in calls:
        totals["calls"] += 1
        totals["charged"] += call.charged
        totals["input_tokens"] += call.input_tokens
        totals["output_tokens"] += call.output_tokens
        day = call.created_at.date().isoformat()
        by_day[day]["calls"] += 1
        by_day[day]["charged"] += call.charged
        by_model[call.model_id]["calls"] += 1
        by_model[call.model_id]["charged"] += call.charged
    labels = _model_labels(db)
    return {
        "days": days,
        "totals": totals,
        "by_day": [{"date": key, **value} for key, value in sorted(by_day.items())],
        "by_model": [
            {"model_id": key, "label": labels.get(key, key), **value}
            for key, value in sorted(by_model.items(), key=lambda item: -item[1]["charged"])
        ],
    }


def mark_order_refunded(
    db: Session, order_id: str, *, amount_cents: int | None, note: str, at: datetime
) -> CloudOrder:
    order = db.get(CloudOrder, order_id)
    if order is None:
        raise CloudError(404, "order_not_found")
    if order.status != "paid":
        raise CloudError(409, "order_not_refundable")
    amount = order.amount_cents if amount_cents is None else amount_cents
    if amount <= 0 or amount > order.amount_cents:
        raise CloudError(400, "invalid_request")
    if order.refunded_at is not None:
        return order
    order.refunded_at = at
    order.refund_cents = amount
    order.refund_note = note[:300]
    #: 退款收回这一笔买下的那个周期(钱是运营在渠道后台退的;权益在这里收回)。账号已删、没发放过的单没有可收回的。
    subscription = db.get(CloudSubscription, order.subscription_id) if order.subscription_id else None
    plan = db.get(CloudPlan, order.plan_id)
    if subscription is not None and plan is not None:
        credits.revoke_purchase(db, subscription, plan, at=at)
    db.flush()
    return order
