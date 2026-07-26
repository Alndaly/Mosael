from __future__ import annotations

import threading
import logging

import httpx
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import ensure_instance_admin
from app.api.schemas import (
    AiRuntimeConfigOut,
    AiRuntimeConfigUpdate,
    KbEmbeddingConfigOut,
    KbEmbeddingConfigUpdate,
    ProviderDefaultOut,
    ProviderDefaultUpdate,
    ProviderPricingRuleCreate,
    ProviderPricingRuleOut,
    ProviderPricingRuleUpdate,
    ProviderProfileCreate,
    ProviderProfileOut,
    ProviderProfileUpdate,
    VendorFieldOut,
    VendorPresetOut,
)
from app.core.db import SessionLocal
from app.db.models import AiRuntimeConfig, KbEmbeddingConfig, ProviderDefault, ProviderPricingRule, ProviderProfile
from app.domain.provider_defaults import CAPABILITIES
from app.domain import kb
from app.domain.kb import config as kb_config
from app.domain.providers import (
    VENDOR_PRESETS,
    capability_ids_for_vendor,
    effective_capability_ids,
    normalize_capability_ids,
    supports_capability,
)
from app.domain.usage import create_pricing_rule, delete_pricing_rule, update_pricing_rule

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)

def _profile_out(profile: ProviderProfile) -> ProviderProfileOut:
    out = ProviderProfileOut.model_validate(profile)
    out.capability_ids = effective_capability_ids(profile)
    out.key_hint = f"…{profile.api_key[-4:]}" if profile.api_key else ""
    out.extra = _masked_extra(profile)
    out.config = _masked_config(profile)
    return out


def _field_specs(vendor: str) -> list[dict]:
    return list(VENDOR_PRESETS.get(vendor, {}).get("fields", []))  # type: ignore[arg-type]


def _field_storage(spec: dict) -> str:
    return str(spec.get("storage") or "extra")


def _read_config_field(profile: ProviderProfile, spec: dict) -> str:
    storage = _field_storage(spec)
    key = str(spec.get("key", ""))
    if storage == "api_key":
        return profile.api_key or ""
    if storage == "base_url":
        return profile.base_url or ""
    if storage == "default_model":
        return profile.default_model or ""
    value = (profile.extra or {}).get(key)
    return str(value) if value else ""


def _write_config_field(profile: ProviderProfile, spec: dict, value: str) -> None:
    storage = _field_storage(spec)
    key = str(spec.get("key", ""))
    if storage == "api_key":
        profile.api_key = value
        return
    if storage == "base_url":
        profile.base_url = value
        return
    if storage == "default_model":
        profile.default_model = value
        return
    merged = dict(profile.extra or {})
    if value:
        merged[key] = value
    else:
        merged.pop(key, None)
    profile.extra = merged


def _masked_config(profile: ProviderProfile) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in _field_specs(profile.vendor):
        key = str(spec.get("key", ""))
        value = _read_config_field(profile, spec)
        if not key or not value:
            continue
        out[key] = f"…{value[-4:]}" if spec.get("secret") else value
    return out


def _masked_extra(profile: ProviderProfile) -> dict[str, str]:
    """Secret extras leave the server only as a hint; identifiers come back in full.

    An App ID is not a secret and the form needs to show it back, but an AK/SK is — sending
    those to the browser would undo the reason api_key is never serialised either.
    """
    stored = profile.extra or {}
    secret_keys = {
        spec["key"] for spec in _field_specs(profile.vendor) if _field_storage(spec) == "extra" and spec.get("secret")
    }
    out: dict[str, str] = {}
    for key, value in stored.items():
        text_value = str(value or "")
        if not text_value:
            continue
        out[key] = f"…{text_value[-4:]}" if key in secret_keys else text_value
    return out


def merge_profile_extra(profile: ProviderProfile, incoming: dict[str, str]) -> dict[str, str]:
    """Fold a form submission into the stored extras.

    A blank value means different things depending on whether the user could see the field:
    a secret is never sent back to the browser, so a blank one means "unchanged" — clearing it
    on every save would silently destroy a working credential. A visible identifier that comes
    back blank was blanked on purpose, so it clears.
    """
    merged = dict(profile.extra or {})
    secret_keys = {
        spec["key"] for spec in _field_specs(profile.vendor) if _field_storage(spec) == "extra" and spec.get("secret")
    }
    for key, value in incoming.items():
        text_value = (value or "").strip()
        if text_value:
            merged[key] = text_value
        elif key not in secret_keys:
            merged.pop(key, None)
    return merged


def _config_from_body(body: ProviderProfileCreate | ProviderProfileUpdate) -> dict[str, str]:
    return dict(body.config or {})


def _apply_profile_config(profile: ProviderProfile, incoming: dict[str, str], *, creating: bool) -> None:
    preset = VENDOR_PRESETS.get(profile.vendor, {})
    if creating:
        profile.api_key = ""
        profile.base_url = str(preset.get("base_url", "") or "")
        profile.default_model = str(preset.get("default_model", "") or "")
        profile.extra = {}

    specs = _field_specs(profile.vendor)
    for spec in specs:
        key = str(spec.get("key", ""))
        if not key:
            continue
        raw_value = incoming.get(key)
        default_value = str(spec.get("default", "") or "")
        if raw_value is None:
            if creating and default_value:
                _write_config_field(profile, spec, default_value)
            continue

        value = str(raw_value or "").strip()
        if value:
            _write_config_field(profile, spec, value)
            continue

        if spec.get("secret") and not creating:
            continue
        if default_value and creating:
            _write_config_field(profile, spec, default_value)
        else:
            _write_config_field(profile, spec, "")

    missing = [
        str(spec.get("label") or spec.get("key"))
        for spec in specs
        if spec.get("required") and not _read_config_field(profile, spec).strip()
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少必要配置: {', '.join(missing)}")


@router.get("/settings/provider-vendors", response_model=list[VendorPresetOut])
def list_vendor_presets(user: CurrentUser) -> list[VendorPresetOut]:
    return [
        VendorPresetOut(
            vendor=vendor,
            label=preset.get("label", vendor),
            capability_ids=capability_ids_for_vendor(vendor),
            base_url=preset.get("base_url", ""),
            default_model=preset.get("default_model", ""),
            capabilities=preset.get("capabilities", ""),
            fields=[VendorFieldOut(**spec) for spec in preset.get("fields", [])],  # type: ignore[arg-type]
        )
        for vendor, preset in VENDOR_PRESETS.items()
    ]


@router.get("/settings/providers", response_model=list[ProviderProfileOut])
def list_provider_profiles(db: DbSession, user: CurrentUser) -> list[ProviderProfileOut]:
    profiles = db.scalars(select(ProviderProfile).order_by(ProviderProfile.created_at)).all()
    return [_profile_out(profile) for profile in profiles]


@router.post("/settings/providers", response_model=ProviderProfileOut)
def create_provider_profile(body: ProviderProfileCreate, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    ensure_instance_admin(db, user, "credentials")
    profile = ProviderProfile(name=body.name, vendor=body.vendor, capability_ids=normalize_capability_ids(body.capability_ids))
    # 服务端凭据复制:同一把 Key 要配到另一能力的独立档案时,密钥从既有档案
    # 直接拷进新行,不经前端往返(设置接口对密钥只回打码提示,前端本就拿不到)。
    # 先注入 secret 字段,再走常规配置应用 —— 显式传入的值仍可覆盖,必填校验共用。
    incoming = _config_from_body(body)
    if body.copy_credentials_from:
        source = db.get(ProviderProfile, body.copy_credentials_from)
        if source is None:
            raise HTTPException(status_code=404, detail="复制来源档案不存在")
        for spec in _field_specs(body.vendor):
            if not spec.get("secret"):
                continue
            key = str(spec.get("key", ""))
            if incoming.get(key, "").strip():
                continue  # 显式提供的密钥优先
            copied = _read_config_field(source, spec)
            if copied:
                incoming[key] = copied
    _apply_profile_config(profile, incoming, creating=True)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.patch("/settings/providers/{profile_id}", response_model=ProviderProfileOut)
def update_provider_profile(
    profile_id: str, body: ProviderProfileUpdate, db: DbSession, user: CurrentUser
) -> ProviderProfileOut:
    ensure_instance_admin(db, user, "credentials")
    profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Not found")
    patch = body.model_dump(exclude_unset=True)
    if "name" in patch and body.name is not None:
        profile.name = body.name
    if "enabled" in patch and body.enabled is not None:
        profile.enabled = body.enabled
    # 显式传了 capability_ids 才动:[] = 清空能力,null = 回落 vendor 默认,不传 = 不改。
    if "capability_ids" in patch:
        profile.capability_ids = normalize_capability_ids(body.capability_ids)
    incoming = _config_from_body(body)
    if incoming:
        _apply_profile_config(profile, incoming, creating=False)
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.get("/settings/provider-defaults", response_model=list[ProviderDefaultOut])
def list_provider_defaults(db: DbSession, user: CurrentUser) -> list[ProviderDefaultOut]:
    """每种能力的默认供应商+模型;未配置的返回空默认。"""
    rows = {row.capability: row for row in db.scalars(select(ProviderDefault))}
    out: list[ProviderDefaultOut] = []
    for capability in CAPABILITIES:
        row = rows.get(capability)
        out.append(
            ProviderDefaultOut(
                capability=capability,
                provider_profile_id=row.provider_profile_id if row else None,
                model=row.model if row else "",
            )
        )
    return out


@router.put("/settings/provider-defaults/{capability}", response_model=ProviderDefaultOut)
def set_provider_default(
    capability: str, body: ProviderDefaultUpdate, db: DbSession, user: CurrentUser
) -> ProviderDefaultOut:
    ensure_instance_admin(db, user, "credentials")
    if capability not in CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    if body.provider_profile_id:
        profile = db.get(ProviderProfile, body.provider_profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if not supports_capability(profile.vendor, capability):
            raise HTTPException(status_code=422, detail=f"该供应商不支持 {capability} 能力")
    row = db.get(ProviderDefault, capability)
    if row is None:
        row = ProviderDefault(capability=capability)
        db.add(row)
    row.provider_profile_id = body.provider_profile_id or None
    row.model = body.model.strip()
    db.commit()
    db.refresh(row)
    return ProviderDefaultOut(capability=row.capability, provider_profile_id=row.provider_profile_id, model=row.model)


def _pricing_payload_with_profile_defaults(
    db: DbSession,
    payload: dict,
    *,
    existing: ProviderPricingRule | None = None,
) -> dict:
    profile_id = payload.get("provider_profile_id")
    if profile_id is None and "provider_profile_id" not in payload and existing is not None:
        profile_id = existing.provider_profile_id
    capability = payload.get("capability") or (existing.capability if existing is not None else "")
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
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
    ensure_instance_admin(db, user, "credentials")
    payload = _pricing_payload_with_profile_defaults(db, body.model_dump())
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
    ensure_instance_admin(db, user, "credentials")
    rule = db.get(ProviderPricingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Not found")
    patch = _pricing_payload_with_profile_defaults(db, body.model_dump(exclude_unset=True), existing=rule)
    try:
        update_pricing_rule(db, rule, **patch)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(rule)
    return ProviderPricingRuleOut.model_validate(rule)


@router.delete("/settings/provider-pricing-rules/{rule_id}", status_code=204)
def delete_provider_pricing_rule(rule_id: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_instance_admin(db, user, "credentials")
    rule = db.get(ProviderPricingRule, rule_id)
    if rule is not None:
        delete_pricing_rule(db, rule)
        db.commit()
    return Response(status_code=204)


@router.get("/settings/providers/{profile_id}/models", response_model=list[str])
def list_provider_models(profile_id: str, db: DbSession, user: CurrentUser) -> list[str]:
    ensure_instance_admin(db, user, "credentials")
    """列出该供应商可用的对话模型(打 OpenAI 兼容 /models;Ollama 亦支持)。
    取不到时回退到该供应商的默认模型,保证选择器至少有一项。"""
    profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    fallback = [profile.default_model] if profile.default_model else []
    if not profile.base_url:
        return fallback
    try:
        resp = httpx.get(
            f"{profile.base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {profile.api_key}"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        models = sorted({str(item["id"]) for item in data if item.get("id")})
        return models or fallback
    except Exception:  # noqa: BLE001 - 取不到就降级到默认模型
        return fallback


@router.delete("/settings/providers/{profile_id}", status_code=204)
def delete_provider_profile(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_instance_admin(db, user, "credentials")
    profile = db.get(ProviderProfile, profile_id)
    if profile is not None:
        db.delete(profile)
        db.commit()
        kb_config.refresh()  # 嵌入配置可能引用了被删的供应商(FK 已 SET NULL)
    return Response(status_code=204)


def _kb_embedding_out() -> KbEmbeddingConfigOut:
    cfg = kb_config.get()
    return KbEmbeddingConfigOut(
        provider_profile_id=cfg.provider_profile_id, model=cfg.model, dim=cfg.dim, enabled=cfg.enabled
    )


@router.get("/settings/kb-embedding", response_model=KbEmbeddingConfigOut)
def get_kb_embedding(db: DbSession, user: CurrentUser) -> KbEmbeddingConfigOut:
    return _kb_embedding_out()


@router.put("/settings/kb-embedding", response_model=KbEmbeddingConfigOut)
def set_kb_embedding(
    body: KbEmbeddingConfigUpdate, db: DbSession, user: CurrentUser
) -> KbEmbeddingConfigOut:
    ensure_instance_admin(db, user, "credentials")
    if body.provider_profile_id:
        profile = db.get(ProviderProfile, body.provider_profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        if not supports_capability(profile.vendor, "embedding"):
            raise HTTPException(status_code=422, detail="该供应商不支持知识库嵌入能力")
    old = kb_config.get()
    row = db.get(KbEmbeddingConfig, "default")
    if row is None:
        row = KbEmbeddingConfig(id="default")
        db.add(row)
    row.provider_profile_id = body.provider_profile_id
    row.model = body.model.strip()
    row.dim = body.dim
    db.commit()
    kb_config.refresh()

    new = kb_config.get()
    changed = (
        old.provider_profile_id != new.provider_profile_id
        or old.model != new.model
        or old.dim != new.dim
    )
    if changed and new.enabled:
        dim_changed = old.dim != new.dim

        def run() -> None:
            try:
                with SessionLocal() as session:
                    kb.rebuild_all_vectors(session, dim_changed=dim_changed)
            except Exception:  # noqa: BLE001 - background rebuild must not poison request/test processes
                logger.exception("KB embedding rebuild failed")

        threading.Thread(target=run, daemon=True).start()
    return _kb_embedding_out()


@router.get("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def get_ai_runtime(db: DbSession, user: CurrentUser) -> AiRuntimeConfigOut:
    row = db.get(AiRuntimeConfig, "default")
    return AiRuntimeConfigOut(max_retries=row.max_retries if row is not None else 3)


@router.put("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def set_ai_runtime(body: AiRuntimeConfigUpdate, db: DbSession, user: CurrentUser) -> AiRuntimeConfigOut:
    """供应商瞬断时的最大重试次数(工作流 LLM 节点用;见 workflows/executors/ai.py)。"""
    ensure_instance_admin(db, user, "credentials")
    row = db.get(AiRuntimeConfig, "default")
    if row is None:
        row = AiRuntimeConfig(id="default")
        db.add(row)
    row.max_retries = body.max_retries
    db.commit()
    return AiRuntimeConfigOut(max_retries=row.max_retries)
