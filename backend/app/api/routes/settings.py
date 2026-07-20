from __future__ import annotations

import threading

import httpx
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import ensure_instance_admin
from app.api.schemas import (
    CredentialSetRequest,
    CredentialStatusOut,
    KbEmbeddingConfigOut,
    KbEmbeddingConfigUpdate,
    ProviderDefaultOut,
    ProviderDefaultUpdate,
    ProviderProfileCreate,
    ProviderProfileOut,
    ProviderProfileUpdate,
    VendorFieldOut,
    VendorPresetOut,
)
from app.core.db import SessionLocal
from app.db.models import Credential, KbEmbeddingConfig, ProviderDefault, ProviderProfile
from app.domain.provider_defaults import CAPABILITIES
from app.domain import kb
from app.domain.kb import config as kb_config
from app.domain.providers import VENDOR_PRESETS

router = APIRouter(tags=["settings"])

KNOWN_PROVIDERS = ["alibaba", "bytedance", "openai", "google", "kuaishou"]


def _profile_out(profile: ProviderProfile) -> ProviderProfileOut:
    out = ProviderProfileOut.model_validate(profile)
    out.key_hint = f"…{profile.api_key[-4:]}" if profile.api_key else ""
    out.extra = _masked_extra(profile)
    return out


def _field_specs(vendor: str) -> list[dict]:
    return list(VENDOR_PRESETS.get(vendor, {}).get("fields", []))  # type: ignore[arg-type]


def _masked_extra(profile: ProviderProfile) -> dict[str, str]:
    """Secret extras leave the server only as a hint; identifiers come back in full.

    An App ID is not a secret and the form needs to show it back, but an AK/SK is — sending
    those to the browser would undo the reason api_key is never serialised either.
    """
    stored = profile.extra or {}
    secret_keys = {spec["key"] for spec in _field_specs(profile.vendor) if spec.get("secret")}
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
    secret_keys = {spec["key"] for spec in _field_specs(profile.vendor) if spec.get("secret")}
    for key, value in incoming.items():
        text_value = (value or "").strip()
        if text_value:
            merged[key] = text_value
        elif key not in secret_keys:
            merged.pop(key, None)
    return merged


@router.get("/settings/provider-vendors", response_model=list[VendorPresetOut])
def list_vendor_presets(user: CurrentUser) -> list[VendorPresetOut]:
    return [
        VendorPresetOut(
            vendor=vendor,
            label=preset.get("label", vendor),
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
    preset = VENDOR_PRESETS.get(body.vendor, {})
    profile = ProviderProfile(
        name=body.name,
        vendor=body.vendor,
        api_key=body.api_key,
        base_url=body.base_url or preset.get("base_url", ""),
        default_model=body.default_model or preset.get("default_model", ""),
    )
    profile.extra = merge_profile_extra(profile, body.extra)
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
    # extra is merged, never assigned: the generic loop below would overwrite the whole dict
    # with whatever the form sent, deleting every credential the browser was not allowed to
    # read back in the first place.
    incoming_extra = patch.pop("extra", None)
    for key, value in patch.items():
        if value is not None:
            setattr(profile, key, value)
    if incoming_extra is not None:
        profile.extra = merge_profile_extra(profile, incoming_extra)
    db.commit()
    db.refresh(profile)
    return _profile_out(profile)


@router.get("/settings/provider-defaults", response_model=list[ProviderDefaultOut])
def list_provider_defaults(db: DbSession, user: CurrentUser) -> list[ProviderDefaultOut]:
    """每种能力(chat/image/video)的默认供应商+模型;未配置的返回空默认。"""
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
    if body.provider_profile_id and db.get(ProviderProfile, body.provider_profile_id) is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    row = db.get(ProviderDefault, capability)
    if row is None:
        row = ProviderDefault(capability=capability)
        db.add(row)
    row.provider_profile_id = body.provider_profile_id or None
    row.model = body.model.strip()
    db.commit()
    db.refresh(row)
    return ProviderDefaultOut(capability=row.capability, provider_profile_id=row.provider_profile_id, model=row.model)


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
    if body.provider_profile_id and db.get(ProviderProfile, body.provider_profile_id) is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
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
            with SessionLocal() as session:
                kb.rebuild_all_vectors(session, dim_changed=dim_changed)

        threading.Thread(target=run, daemon=True).start()
    return _kb_embedding_out()


@router.get("/settings/credentials", response_model=list[CredentialStatusOut])
def list_credentials(db: DbSession, user: CurrentUser) -> list[CredentialStatusOut]:
    ensure_instance_admin(db, user, "credentials")
    """Secrets never leave the backend — only configured-status and a hint."""
    stored = {credential.provider: credential for credential in db.scalars(select(Credential))}
    providers = sorted(set(KNOWN_PROVIDERS) | set(stored))
    return [
        CredentialStatusOut(
            provider=provider,
            configured=provider in stored,
            hint=f"…{stored[provider].secret[-4:]}" if provider in stored else "",
        )
        for provider in providers
    ]


@router.put("/settings/credentials", response_model=CredentialStatusOut)
def set_credential(body: CredentialSetRequest, db: DbSession, user: CurrentUser) -> CredentialStatusOut:
    ensure_instance_admin(db, user, "credentials")
    credential = db.get(Credential, body.provider)
    if credential is None:
        credential = Credential(provider=body.provider, secret=body.secret)
        db.add(credential)
    else:
        credential.secret = body.secret
    db.commit()
    return CredentialStatusOut(provider=body.provider, configured=True, hint=f"…{body.secret[-4:]}")


@router.delete("/settings/credentials/{provider}", status_code=204)
def delete_credential(provider: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_instance_admin(db, user, "credentials")
    credential = db.get(Credential, provider)
    if credential is not None:
        db.delete(credential)
        db.commit()
    return Response(status_code=204)
