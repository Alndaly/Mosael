from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.ai.model_catalog import fetch_models
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    PricingPrefillOut,
    ProviderPricingRuleCreate,
    ProviderPricingRuleOut,
    ProviderPricingRuleUpdate,
)
from app.db.models import ProviderPricingRule
from app.domain import provider_credentials
from app.domain.permissions import ensure_deployment_admin
from app.domain.provider_credentials import ResolvedConnection
from app.domain.providers import supports_capability
from app.domain.usage import create_pricing_rule, delete_pricing_rule, prefill_model_pricing, update_pricing_rule

from .provider_profiles import _require_profile

router = APIRouter(tags=["settings"])

def _catalog_rates(profile: ResolvedConnection) -> list[tuple[str, dict[str, float | None]]]:
    """(模型 id, 每百万 token 报价) —— 两种档案取自各自的目录来源,单位已对齐。

    参数是**解析过的**连接(连接 + 这个人的钥匙):订阅目录在他自己那把钥匙上,API Key 档案
    要拿他的钥匙去打 /models。
    """
    if profile.auth_type == "oauth":
        # 订阅计划:登录时 pi 带回来的目录(cost 是 {input, output, cacheRead, cacheWrite})。
        out = []
        for item in profile.model_catalog or []:
            model_id = str(item.get("id", ""))
            cost = item.get("cost") or {}
            if model_id and isinstance(cost, dict):
                out.append(
                    (
                        model_id,
                        {
                            "input": cost.get("input"),
                            "output": cost.get("output"),
                            "cache_read": cost.get("cacheRead"),
                            "cache_write": cost.get("cacheWrite"),
                        },
                    )
                )
        return out
    # API Key 档案:现取 /models。多数端点不报价,报价的(OpenRouter 一类)在 pricing 里给每 token 价。
    return [
        (
            m.id,
            {
                "input": m.input_cost,
                "output": m.output_cost,
                "cache_read": m.cache_read_cost,
                "cache_write": m.cache_write_cost,
            },
        )
        for m in fetch_models(profile.base_url or "", profile.api_key or "")
    ]


@router.post("/settings/providers/{profile_id}/pricing/prefill", response_model=PricingPrefillOut)
def prefill_provider_pricing(profile_id: str, db: DbSession, user: CurrentUser) -> PricingPrefillOut:
    """按该供应商的模型目录补齐缺失的计价规则。

    **只补不改**:已有规则一概不动 —— 目录报价是厂商挂牌价,用户填过的才是他核对过的账。
    目录里为 0 的项也不写(那是「未标价 / 订阅内含」,不是「免费」)。
    """
    ensure_deployment_admin(db, user)
    profile = _require_profile(db, profile_id, user)
    resolved = provider_credentials.resolve_connection(db, profile, user.id)
    if resolved is None:
        raise HTTPException(status_code=422, detail="这条连接还没有你的密钥,先填一把再来取目录报价")
    rates = _catalog_rates(resolved)
    created = 0
    priced = 0
    for model_id, model_rates in rates:
        if any(value for value in model_rates.values()):
            priced += 1
        created += prefill_model_pricing(
            db,
            provider_profile_id=profile.id,
            provider=profile.vendor,
            model=model_id,
            rates=model_rates,
        )
    db.commit()
    return PricingPrefillOut(created=created, models_with_price=priced, models_seen=len(rates))



def _pricing_payload_with_profile_defaults(
    db: DbSession,
    payload: dict,
    *,
    user: CurrentUser,
    existing: ProviderPricingRule | None = None,
) -> dict:
    profile_id = payload.get("provider_profile_id")
    if profile_id is None and "provider_profile_id" not in payload and existing is not None:
        profile_id = existing.provider_profile_id
    capability = payload.get("capability") or (existing.capability if existing is not None else "")
    if profile_id:
        profile = _require_profile(db, profile_id, user)
        if capability and not supports_capability(profile.vendor, capability):
            raise HTTPException(status_code=422, detail=f"该供应商不支持 {capability} 能力")
        if not payload.get("provider"):
            payload["provider"] = profile.vendor
    return payload


@router.get("/settings/provider-pricing-rules", response_model=list[ProviderPricingRuleOut])
def list_provider_pricing_rules(
    db: DbSession, user: CurrentUser, workspace_id: str | None = None
) -> list[ProviderPricingRuleOut]:
    stmt = select(ProviderPricingRule).order_by(
        ProviderPricingRule.capability.asc(),
        ProviderPricingRule.provider.asc(),
        ProviderPricingRule.model.asc(),
        ProviderPricingRule.created_at.asc(),
    )
    if workspace_id:
        stmt = stmt.where(ProviderPricingRule.workspace_id == workspace_id)
    rules = db.scalars(stmt).all()
    return [ProviderPricingRuleOut.model_validate(rule) for rule in rules]


@router.post("/settings/provider-pricing-rules", response_model=ProviderPricingRuleOut)
def create_provider_pricing_rule(
    body: ProviderPricingRuleCreate, db: DbSession, user: CurrentUser
) -> ProviderPricingRuleOut:
    ensure_deployment_admin(db, user)
    payload = _pricing_payload_with_profile_defaults(db, body.model_dump(), user=user)
    try:
        rule = create_pricing_rule(db, **payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(rule)
    return ProviderPricingRuleOut.model_validate(rule)


@router.patch("/settings/provider-pricing-rules/{rule_id}", response_model=ProviderPricingRuleOut)
def update_provider_pricing_rule(
    rule_id: str, body: ProviderPricingRuleUpdate, db: DbSession, user: CurrentUser
) -> ProviderPricingRuleOut:
    ensure_deployment_admin(db, user)
    rule = db.get(ProviderPricingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Not found")
    patch = _pricing_payload_with_profile_defaults(
        db,
        body.model_dump(exclude_unset=True),
        user=user,
        existing=rule,
    )
    try:
        update_pricing_rule(db, rule, **patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(rule)
    return ProviderPricingRuleOut.model_validate(rule)


@router.delete("/settings/provider-pricing-rules/{rule_id}", status_code=204)
def delete_provider_pricing_rule(rule_id: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_deployment_admin(db, user)
    rule = db.get(ProviderPricingRule, rule_id)
    if rule is not None:
        delete_pricing_rule(db, rule)
        db.commit()
    return Response(status_code=204)


