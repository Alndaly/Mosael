from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    PricingPrefillOut,
    ProviderPricingRuleCreate,
    ProviderPricingRuleOut,
    ProviderPricingRuleUpdate,
)
from app.db.models import ProviderPricingRule
from app.domain.providers import credentials as provider_credentials
from app.domain.providers import models as provider_models
from app.domain.permissions import ensure_deployment_admin
from app.domain.providers.credentials import ResolvedConnection
from app.domain.providers.selection import supports_capability
from app.domain.billing import use_cases as billing
from app.domain.billing.pricing_prefill import prefill_profile_pricing
from app.domain.billing.usage import create_pricing_rule, delete_pricing_rule, update_pricing_rule

from app.domain.permissions import require_own_profile

router = APIRouter(tags=["settings"])

def _catalog_rates(connection: ResolvedConnection) -> list[tuple[str, dict[str, float | None]]]:
    """(模型 id, 每百万 token 报价)。多数 API Key 端点不报价,报价的(OpenRouter 一类)和订阅目录
    都在这里对齐成同一个单位(来源见 provider_models.catalog)。"""
    return [
        (
            model.id,
            {
                "input": model.input_cost,
                "output": model.output_cost,
                "cache_read": model.cache_read_cost,
                "cache_write": model.cache_write_cost,
            },
        )
        for model in provider_models.catalog(connection)
    ]


@router.post("/settings/providers/{profile_id}/pricing/prefill", response_model=PricingPrefillOut)
def prefill_provider_pricing(profile_id: str, db: DbSession, user: CurrentUser) -> PricingPrefillOut:
    """给这条连接的模型补齐缺失的计价规则:端点目录的报价优先,官方价目表补缺。

    **只补不改**:已有规则一概不动 —— 目录和价目表都是厂商挂牌价,用户填过的才是他核对过的账。
    为 0 的报价也不写(那是「未标价 / 订阅内含」,不是「免费」)。见 domain/billing/pricing_prefill。
    """
    ensure_deployment_admin(db, user)
    profile = require_own_profile(db, user, profile_id)
    resolved = provider_credentials.resolve_connection(db, profile, user.id)
    if resolved is None:
        raise HTTPException(status_code=422, detail=tr("routeErr_pricingNeedsKey"))
    outcome = prefill_profile_pricing(
        db, profile, base_url=resolved.base_url or "", catalog=_catalog_rates(resolved)
    )
    db.commit()
    return PricingPrefillOut(
        created=outcome.created,
        created_from_catalog=outcome.created_from_catalog,
        created_from_reference=outcome.created_from_reference,
        created_with_time_prices=outcome.created_with_time_prices,
        models_seen=outcome.models_seen,
        models_with_price=outcome.models_with_price,
        unpriced_models=outcome.unpriced_models,
    )


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
        profile = require_own_profile(db, user, profile_id)
        if capability and not supports_capability(profile.vendor, capability):
            raise HTTPException(status_code=422, detail=tr("routeErr_providerLacksCapability", capability=capability))
        if not payload.get("provider"):
            payload["provider"] = profile.vendor
    return payload


@router.get("/settings/provider-pricing-rules", response_model=list[ProviderPricingRuleOut])
def list_provider_pricing_rules(
    db: DbSession, user: CurrentUser, workspace_id: str | None = None
) -> list[ProviderPricingRuleOut]:
    """这个工作区的计价规则。

    **不给 workspace_id 就是看全库** —— 那是这台机器的运维视图,只给部署管理员:此前它对任何
    登录用户开放,于是 A 工作区的成员能读到 B 工作区谈下来的单价。写入一直是 deployment admin,
    读却没有门 —— 一张表两套判据,漏的那一半不会报错。
    """
    return [ProviderPricingRuleOut.model_validate(rule) for rule in billing.list_pricing_rules(db, user, workspace_id)]


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


