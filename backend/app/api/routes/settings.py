from __future__ import annotations

import threading
import time
import logging

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import ensure_instance_admin
from app.ai.agent.login import (
    LoginError,
    answer as answer_login,
    cancel as cancel_login,
    get_session as get_login_session,
    start_login,
)
from app.ai.model_catalog import fetch_models
from app.api.schemas import (
    OAuthAnswerIn,
    PricingPrefillOut,
    OAuthLoginOut,
    OAuthPromptOut,
    ProviderModelOut,
    AiRuntimeConfigOut,
    AiRuntimeConfigUpdate,
    NetworkConfigOut,
    NetworkConfigUpdate,
    KbEmbeddingConfigOut,
    KbEmbeddingConfigUpdate,
    CapabilityModelOut,
    ProviderDefaultOut,
    ProviderDefaultUpdate,
    ProviderPricingRuleCreate,
    ProviderPricingRuleOut,
    ProviderPricingRuleUpdate,
    ProviderHealthOut,
    ProviderProfileCreate,
    ProviderModelUpdate,
    ProviderQuotaOut,
    ProviderProfileOut,
    ProviderProfileUpdate,
    VendorFieldOut,
    VendorPresetOut,
)
from app.core.config import settings as settings_config
from app.core.db import SessionLocal
from app.db.models import (
    AiRuntimeConfig,
    NetworkConfig,
    KbEmbeddingConfig,
    ProviderDefault,
    ProviderPricingRule,
    ProviderProfile,
    new_id,
)
from app.domain.provider_defaults import CAPABILITIES, set_default
from app.domain import kb
from app.domain.kb import config as kb_config
from app.domain.network import apply_to_process, effective_no_proxy, get_config as get_network
from app.ai.agent.adapters import AdapterError, refresh_oauth_credential
from app.ai.agent.host import mint_tool_token
from app.domain import provider_models
from app.domain.ai_retry import set_max_retries
from app.domain.provider_quota import QuotaUnavailable, fetch_quota, is_expired, supports_quota
from app.domain import provider_health
from app.domain.provider_auth import acquire_lease, commit_credential, read_credential
from app.domain.providers import (
    VENDOR_PRESETS,
    pi_provider_id,
    auth_types_for_vendor,
    capability_ids_for_vendor,
    effective_capability_ids,
    normalize_auth_type,
    normalize_capability_ids,
    supports_capability,
)
from app.domain.usage import (
    create_pricing_rule,
    delete_pricing_rule,
    prefill_model_pricing,
    update_pricing_rule,
)

router = APIRouter(tags=["settings"])
logger = logging.getLogger(__name__)

def _profile_out(db: DbSession, profile: ProviderProfile) -> ProviderProfileOut:
    out = ProviderProfileOut.model_validate(profile)
    # 连接对外提供的能力 = 它下面所有启用模型能力的并集(没有模型行时回落 vendor 预设)。
    out.capability_ids = provider_models.profile_capabilities(db, profile)
    out.key_hint = f"…{profile.api_key[-4:]}" if profile.api_key else ""
    out.extra = _masked_extra(profile)
    out.config = _masked_config(db, profile)
    # 令牌本身不下发,只说「登上了没有」——UI 需要的也只有这个。
    out.oauth_linked = bool(profile.oauth_credential)
    out.quota_supported = supports_quota(pi_provider_id(profile.vendor))
    out.oauth_expired = out.oauth_linked and is_expired(read_credential(profile))
    return out


def _field_specs(vendor: str) -> list[dict]:
    return list(VENDOR_PRESETS.get(vendor, {}).get("fields", []))  # type: ignore[arg-type]


def _field_storage(spec: dict) -> str:
    return str(spec.get("storage") or "extra")


def _read_config_field(db: DbSession, profile: ProviderProfile, spec: dict) -> str:
    storage = _field_storage(spec)
    key = str(spec.get("key", ""))
    if storage == "api_key":
        return profile.api_key or ""
    if storage == "base_url":
        return profile.base_url or ""
    if storage == "default_model":
        # 这个表单项现在落到模型行,不再存在档案上。读回来时取这条连接在它主能力下的模型 ——
        # 绝大多数连接只有一个模型,读到的就是用户当初填的那个。
        capabilities = provider_models.profile_capabilities(db, profile)
        return provider_models.model_id_for(db, profile, capabilities[0]) if capabilities else ""
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
        # 由 _sync_model_row 建成模型行(它需要 db,而这里只拿得到 profile)。
        return
    merged = dict(profile.extra or {})
    if value:
        merged[key] = value
    else:
        merged.pop(key, None)
    profile.extra = merged


def _masked_config(db: DbSession, profile: ProviderProfile) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in _field_specs(profile.vendor):
        key = str(spec.get("key", ""))
        value = _read_config_field(db, profile, spec)
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


def _apply_profile_config(db: DbSession, profile: ProviderProfile, incoming: dict[str, str], *, creating: bool) -> None:
    preset = VENDOR_PRESETS.get(profile.vendor, {})
    if creating:
        profile.api_key = ""
        profile.base_url = str(preset.get("base_url", "") or "")
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

    def _submitted(spec: dict) -> str:
        """校验用的值。default_model 这类字段落成的是模型行,而模型行在校验**之后**才建 ——
        拿"读回来的模型"去判必填永远是空,新建档案会一律报缺少默认模型。"""
        key = str(spec.get("key", ""))
        if _field_storage(spec) == "default_model":
            return (incoming.get(key) or str(spec.get("default", "") or "")).strip() or _read_config_field(
                db, profile, spec
            )
        return _read_config_field(db, profile, spec)

    missing = [
        str(spec.get("label") or spec.get("key"))
        for spec in specs
        if spec.get("required") and not _submitted(spec).strip()
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
            auth=auth_types_for_vendor(vendor),
        )
        for vendor, preset in VENDOR_PRESETS.items()
    ]


#: 刷新失败后多久才再试一次。失败通常不会因为再试而变好(refresh token 被吊销、账号在别处
#: 登出),而档案列表是设置页最常被拉的那个接口 —— 没有冷却就会变成每次进页面都起一次
#: node 去撞同一堵墙,页面还跟着卡。
_REFRESH_COOLDOWN_SECONDS = 300.0
_refresh_failed_at: dict[str, float] = {}


def _auto_refresh_expired(db: DbSession, user: CurrentUser, profiles) -> None:
    """过期就先刷一次,而不是把「令牌已过期」摆出来让用户自己去想办法。

    **过期本身不是一个需要用户知道的状态**:订阅计划的 access token 普遍只有几小时,
    刷新是协议里就有的一步。此前只有对话路径(pi 解析鉴权时)和查额度会触发刷新,于是
    "隔夜再打开设置页"必然看到一行已过期 —— 而它其实只要被用到就会自己好。

    刷新协议仍然在 pi 那边(见 refresh_oauth_credential),这里只负责决定什么时候刷。
    刷不动才让 oauth_expired 保持 True —— 那时它是真的需要用户重新授权。
    """
    now = time.monotonic()
    for profile in profiles:
        if profile.auth_type != "oauth" or not profile.oauth_credential:
            continue
        credential = read_credential(profile)
        if credential is None or not is_expired(credential):
            _refresh_failed_at.pop(profile.id, None)
            continue
        failed_at = _refresh_failed_at.get(profile.id)
        if failed_at is not None and now - failed_at < _REFRESH_COOLDOWN_SECONDS:
            continue
        try:
            refresh_oauth_credential(
                api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
                token=mint_tool_token(db, user),
                pi_provider=pi_provider_id(profile.vendor) or "",
                profile_id=profile.id,
                credential=credential,
            )
        except AdapterError as exc:
            logger.warning("刷新 %s 的订阅令牌失败:%s", profile.name, exc)
            _refresh_failed_at[profile.id] = now
            continue
        _refresh_failed_at.pop(profile.id, None)
        db.refresh(profile)


@router.get("/settings/providers", response_model=list[ProviderProfileOut])
def list_provider_profiles(db: DbSession, user: CurrentUser) -> list[ProviderProfileOut]:
    profiles = db.scalars(select(ProviderProfile).order_by(ProviderProfile.created_at)).all()
    _auto_refresh_expired(db, user, profiles)
    return [_profile_out(db, profile) for profile in profiles]


def _sync_model_row(db: DbSession, profile: ProviderProfile, incoming: dict[str, str]) -> None:
    """表单里那个「模型」字段落成模型行。

    档案上不再有 default_model —— 那是"一档案一模型"时代的字段。表单项保留是因为建连接时
    顺手填一个模型确实是常见流程,但它写进的是 provider_models 的一行,和后来在模型列表里
    加的那些完全平权。

    能力留空,由 effective_capabilities 回落 vendor 预设;用户想细分就去模型列表里改。
    """
    preset = VENDOR_PRESETS.get(profile.vendor, {})
    specs = [spec for spec in _field_specs(profile.vendor) if _field_storage(spec) == "default_model"]
    model_id = ""
    for spec in specs:
        key = str(spec.get("key", ""))
        model_id = (incoming.get(key) or str(spec.get("default", "") or "")).strip()
        if model_id:
            break
    if not model_id:
        model_id = str(preset.get("default_model", "") or "").strip()
    if not model_id:
        return
    provider_models.upsert(db, profile, model_id, source="manual")


@router.post("/settings/providers", response_model=ProviderProfileOut)
def create_provider_profile(body: ProviderProfileCreate, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    ensure_instance_admin(db, user, "credentials")
    profile = ProviderProfile(
        name=body.name,
        vendor=body.vendor,
        auth_type=normalize_auth_type(body.vendor, body.auth_type),
    )
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
            copied = _read_config_field(db, source, spec)
            if copied:
                incoming[key] = copied
    _apply_profile_config(db, profile, incoming, creating=True)
    db.add(profile)
    db.flush()
    _sync_model_row(db, profile, incoming)
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile)


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
    # 能力现在挂在模型行上(见 provider_models),不再是档案级覆盖 —— 同一个端点既可能有
    # 对话模型也可能有生图模型,挂在连接上就只能二选一。
    if "auth_type" in patch and body.auth_type is not None:
        # 切换鉴权方式时清掉另一侧的凭据:留着的那份既不会被用到,又会让「已登录」的显示说谎。
        next_auth = normalize_auth_type(profile.vendor, body.auth_type)
        if next_auth != profile.auth_type:
            profile.auth_type = next_auth
            if next_auth == "api_key":
                profile.oauth_credential = None
            else:
                profile.api_key = ""
            profile.credential_version = (profile.credential_version or 0) + 1
    incoming = _config_from_body(body)
    if incoming:
        _apply_profile_config(db, profile, incoming, creating=False)
    db.flush()
    _sync_model_row(db, profile, incoming)
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile)


def _require_profile(db: DbSession, profile_id: str) -> ProviderProfile:
    profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return profile


def _oauth_profile(db: DbSession, profile_id: str) -> ProviderProfile:
    profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if profile.auth_type != "oauth" or not pi_provider_id(profile.vendor):
        raise HTTPException(status_code=400, detail="该供应商不是订阅计划,不需要授权登录")
    return profile


def _login_out(session, db: DbSession | None = None) -> OAuthLoginOut:
    return OAuthLoginOut(
        login_id=session.login_id,
        status=session.status,
        events=list(session.events),
        prompt=OAuthPromptOut(**session.prompt) if session.prompt else None,
        error=session.error,
        models=[
            ProviderModelOut(
                id=str(item.get("id", "")),
                context_window=item.get("contextWindow"),
                max_output_tokens=item.get("maxTokens"),
            )
            for item in session.models
            if item.get("id")
        ],
    )


def _store_login_catalog(db: DbSession, profile: ProviderProfile, session) -> None:
    """登录成功后把该账号的模型目录落库,并在没有默认模型时先挑一个。

    不挑的话用户回到设置页只会看到一个空的模型选择器,而「登录成功但用不了」比登录失败更费解。
    """
    if session.status != "done" or not session.models:
        return
    profile.model_catalog = session.models
    # 登录带回目录后,若这条连接一个模型行都没有,先把第一个建上 ——
    # 否则「登录成功但用不了」,比登录失败更费解。
    if not provider_models.list_models(db, profile.id):
        first = str(session.models[0].get("id", "")).strip()
        if first:
            provider_models.upsert(db, profile, first, source="catalog")
    db.commit()


@router.post("/settings/providers/{profile_id}/oauth/login", response_model=OAuthLoginOut)
def start_oauth_login(profile_id: str, db: DbSession, user: CurrentUser) -> OAuthLoginOut:
    """发起订阅计划的授权登录。返回的状态里会陆续出现授权链接 / 设备码,前端轮询展示。"""
    ensure_instance_admin(db, user, "credentials")
    profile = _oauth_profile(db, profile_id)
    from app.ai.agent.host import mint_tool_token

    try:
        session = start_login(
            login_id=new_id(),
            profile_id=profile.id,
            pi_provider=pi_provider_id(profile.vendor),
            api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
            token=mint_tool_token(db, user),
            credential=read_credential(profile),
        )
    except LoginError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _login_out(session)


@router.get("/settings/providers/{profile_id}/oauth/login/{login_id}", response_model=OAuthLoginOut)
def poll_oauth_login(profile_id: str, login_id: str, db: DbSession, user: CurrentUser) -> OAuthLoginOut:
    ensure_instance_admin(db, user, "credentials")
    profile = _oauth_profile(db, profile_id)
    session = get_login_session(login_id)
    if session is None or session.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="登录会话已结束")
    _store_login_catalog(db, profile, session)
    return _login_out(session)


@router.post("/settings/providers/{profile_id}/oauth/login/{login_id}/answer", response_model=OAuthLoginOut)
def answer_oauth_login(
    profile_id: str, login_id: str, body: OAuthAnswerIn, db: DbSession, user: CurrentUser
) -> OAuthLoginOut:
    ensure_instance_admin(db, user, "credentials")
    _oauth_profile(db, profile_id)
    session = get_login_session(login_id)
    if session is None or session.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="登录会话已结束")
    if not answer_login(login_id, body.prompt_id, body.answer):
        raise HTTPException(status_code=409, detail="这一步已经不在等待作答了")
    return _login_out(session)


@router.delete("/settings/providers/{profile_id}/oauth/login/{login_id}", status_code=204)
def cancel_oauth_login(profile_id: str, login_id: str, db: DbSession, user: CurrentUser) -> None:
    ensure_instance_admin(db, user, "credentials")
    _oauth_profile(db, profile_id)
    cancel_login(login_id)


@router.get("/settings/providers/{profile_id}/health", response_model=ProviderHealthOut)
def probe_provider_health(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderHealthOut:
    """探一次这条连接通不通、往返多久。

    **只在被问到时探**,不做后台轮询:探针会真的打到用户的端点上(本地 ComfyUI、云端 /models),
    定时轮询等于替用户持续产生请求 —— 而"它现在通不通"这个问题只在他看着这一页时才有意义。
    """
    profile = _require_profile(db, profile_id)
    result = provider_health.probe(profile)
    return ProviderHealthOut(
        supported=result.supported,
        online=result.online,
        latency_ms=result.latency_ms,
        detail=result.detail,
    )


@router.post("/settings/providers/{profile_id}/quota", response_model=ProviderQuotaOut)
def fetch_provider_quota(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderQuotaOut:
    """查一次订阅额度。

    **只在用户点击时执行**,不做后台轮询:这些端点都不是官方承诺的公开接口(Anthropic 的
    oauth/usage、Codex 的 codex/usage 都是各自 CLI 内部在用),定时轮询既容易撞限流,也会
    在对方改接口后变成后台里一直失败的任务。

    查不到不抛 5xx:"这家不支持"和"这次没查成"都是正常结果,前端要据此显示不同的话,
    500 会被统一的错误提示吞成一句"请求失败"。
    """
    ensure_instance_admin(db, user, "credentials")
    profile = _oauth_profile(db, profile_id)
    pi_provider = pi_provider_id(profile.vendor)
    if not supports_quota(pi_provider):
        return ProviderQuotaOut(supported=False)
    credential = read_credential(profile)
    # 令牌过期就先刷新再查。自动刷新原本只发生在对话路径上(pi 解析模型鉴权时按 expires 判),
    # 于是"很久没聊天"之后这条旁路一律撞 401,而档案上明明写着已授权。刷新协议仍在 pi 那边,
    # 这里只是让它跑一次。
    if credential is not None and is_expired(credential):
        try:
            refresh_oauth_credential(
                api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
                token=mint_tool_token(db, user),
                pi_provider=pi_provider or "",
                profile_id=profile.id,
                credential=credential,
            )
            db.refresh(profile)
            credential = read_credential(profile)
        except AdapterError as exc:
            return ProviderQuotaOut(supported=True, error=f"令牌刷新失败:{exc}")
    try:
        snapshot = fetch_quota(pi_provider, credential)
    except QuotaUnavailable as exc:
        return ProviderQuotaOut(supported=True, error=str(exc))
    return ProviderQuotaOut(supported=True, **snapshot)


@router.delete("/settings/providers/{profile_id}/oauth", response_model=ProviderProfileOut)
def logout_oauth_provider(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    """解除该档案的订阅登录。登出是应用侧动作,跑对话的 sidecar 无权做(见 credentials.ts)。"""
    ensure_instance_admin(db, user, "credentials")
    profile = _oauth_profile(db, profile_id)
    lease = acquire_lease(profile.id)
    commit_credential(db, profile.id, lease, None)
    profile.model_catalog = None
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile)


def _catalog_rates(profile: ProviderProfile) -> list[tuple[str, dict[str, float | None]]]:
    """(模型 id, 每百万 token 报价) —— 两种档案取自各自的目录来源,单位已对齐。"""
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
    ensure_instance_admin(db, user, "credentials")
    profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    rates = _catalog_rates(profile)
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


@router.get("/settings/capability-models/{capability}", response_model=list[CapabilityModelOut])
def list_capability_models(capability: str, db: DbSession, user: CurrentUser) -> list[CapabilityModelOut]:
    """某能力下所有可用模型,跨连接。

    界面直接列它,而不是"先选供应商再选模型" —— 后者是模型还不是实体时的形状,逼着用户
    先知道"这个模型在哪条连接下",而那恰恰是他不关心的事。
    """
    ensure_instance_admin(db, user, "credentials")
    if capability not in CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    return [
        CapabilityModelOut(
            provider_profile_id=model.provider_profile_id,
            provider_name=model.profile.name if model.profile is not None else "",
            model=model.model_id,
            display_name=model.display_name or "",
        )
        for model in provider_models.models_for_capability(db, capability)
    ]


@router.put("/settings/provider-defaults/{capability}", response_model=ProviderDefaultOut)
def set_provider_default(
    capability: str, body: ProviderDefaultUpdate, db: DbSession, user: CurrentUser
) -> ProviderDefaultOut:
    ensure_instance_admin(db, user, "credentials")
    if capability not in CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    model = None
    model_id = body.model.strip()
    if body.provider_profile_id and model_id:
        profile = db.get(ProviderProfile, body.provider_profile_id)
        if profile is None:
            raise HTTPException(status_code=404, detail="供应商不存在")
        model = provider_models.get_model(db, body.provider_profile_id, model_id)
        # 能力校验放在建行之前:先建再拒会在库里留下一行没人要的模型。
        # 已有行按它自己的能力判,没有行按 vendor 预设判(新行正是这么回落的)。
        capabilities = (
            provider_models.effective_capabilities(model)
            if model is not None
            else capability_ids_for_vendor(profile.vendor)
        )
        if capability not in capabilities:
            raise HTTPException(status_code=422, detail=f"该模型不提供 {capability} 能力")
        if model is None:
            # 设默认时顺手把这一行加上 —— 用户知道模型名但还没加过它是个正常流程,
            # 逼他先去列表里加一遍纯属多一步。
            model = provider_models.upsert(db, profile, model_id, source="manual")
    # 指向模型行(旧的两列由 set_default 同步写,生成侧还在读)。
    set_default(db, capability, model)
    db.commit()
    row = db.get(ProviderDefault, capability)
    return ProviderDefaultOut(
        capability=capability,
        provider_profile_id=row.provider_profile_id if row else None,
        model=row.model if row else "",
    )


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


def _catalog_entries(profile: ProviderProfile) -> dict[str, dict]:
    """该连接的**目录**(供应商说它有什么)。订阅计划的目录只有登录才知道(Copilot 随档位变、
    OpenRouter 有几百个),登录时由 pi 带回存下;API Key 档案现打 /models(带 TTL 缓存)。"""
    if profile.auth_type == "oauth":
        return {
            str(item.get("id")): {
                "context_window": item.get("contextWindow"),
                "max_output_tokens": item.get("maxTokens"),
            }
            for item in (profile.model_catalog or [])
            if isinstance(item, dict) and item.get("id")
        }
    return {
        m.id: {"context_window": m.context_window, "max_output_tokens": m.max_output_tokens}
        for m in fetch_models(profile.base_url or "", profile.api_key or "")
    }


def _model_out(model, catalog: dict[str, dict]) -> ProviderModelOut:
    entry = catalog.get(model.model_id) or {}
    catalog_window = entry.get("context_window")
    if model.context_window:
        window, source = model.context_window, "override"
    elif catalog_window:
        window, source = catalog_window, "catalog"
    else:
        window, source = None, "fallback"
    return ProviderModelOut(
        id=model.model_id,
        display_name=model.display_name or "",
        capability_ids=list(model.capability_ids or []),
        effective_capability_ids=provider_models.effective_capabilities(model),
        enabled=model.enabled,
        configured=True,
        in_catalog=model.model_id in catalog,
        source=model.source,
        context_window=window,
        context_window_source=source,
        max_output_tokens=model.max_output_tokens or entry.get("max_output_tokens"),
        reasoning=model.reasoning,
        vision=model.vision,
        reasoning_effort=model.reasoning_effort,
        developer_role=model.developer_role,
    )


@router.get("/settings/providers/{profile_id}/models", response_model=list[ProviderModelOut])
def list_provider_models(profile_id: str, db: DbSession, user: CurrentUser) -> list[ProviderModelOut]:
    """这条连接下的模型:**已配置的行 + 目录里还没配的**。

    两者合并而不是二选一 —— 目录说端点有什么(会变),模型行说用户做过什么(不该被目录冲掉)。
    已配置的排在前面:那是用户实际在用的;目录里的其余项跟在后面,可一键加入。
    """
    ensure_instance_admin(db, user, "credentials")
    profile = _require_profile(db, profile_id)
    catalog = _catalog_entries(profile)
    configured = provider_models.list_models(db, profile_id)
    rows = [_model_out(model, catalog) for model in configured]
    known = {row.id for row in rows}
    for model_id, entry in catalog.items():
        if model_id in known:
            continue
        rows.append(
            ProviderModelOut(
                id=model_id,
                configured=False,
                in_catalog=True,
                enabled=False,  # 没配置过 = 还没启用,加入后才进选择器
                context_window=entry.get("context_window"),
                context_window_source="catalog" if entry.get("context_window") else "fallback",
                max_output_tokens=entry.get("max_output_tokens"),
                effective_capability_ids=capability_ids_for_vendor(profile.vendor),
            )
        )
    return rows


@router.post("/settings/providers/{profile_id}/models", response_model=ProviderModelOut)
def add_provider_model(
    profile_id: str, body: ProviderModelUpdate, db: DbSession, user: CurrentUser
) -> ProviderModelOut:
    """把一个模型加进这条连接。目录里选的和手填的走同一条路 —— 区别只在 source,
    手填是为了私有部署与别名:目录查不到不等于不能用。"""
    ensure_instance_admin(db, user, "credentials")
    profile = _require_profile(db, profile_id)
    model_id = (body.model_id or "").strip()
    if not model_id:
        raise HTTPException(status_code=422, detail="模型 id 不能为空")
    catalog = _catalog_entries(profile)
    fields = body.model_dump(exclude_unset=True, exclude={"model_id", "capability_ids"})
    model = provider_models.upsert(
        db,
        profile,
        model_id,
        source="catalog" if model_id in catalog else "manual",
        capability_ids=body.capability_ids if body.capability_ids is not None else None,
        **fields,
    )
    db.commit()
    return _model_out(model, catalog)


@router.patch("/settings/providers/{profile_id}/models/{model_id:path}", response_model=ProviderModelOut)
def update_provider_model(
    profile_id: str, model_id: str, body: ProviderModelUpdate, db: DbSession, user: CurrentUser
) -> ProviderModelOut:
    """改一行。

    **model_id 必须用 :path 转换器**:模型 id 里带斜杠是常态(kimi/kimi-k2.7-code、
    MiniMax/MiniMax-M2.5、ZHIPU/GLM-5),而普通路径参数不跨 `/`,路由直接匹配不上 ——
    表现是删除/修改一律 404,而且只有那些带斜杠的模型才复现。
    运行时项传 null 即清除、回到跟随目录 —— 与"没传"是两回事,后者不动它。"""
    ensure_instance_admin(db, user, "credentials")
    profile = _require_profile(db, profile_id)
    model = provider_models.get_model(db, profile_id, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="该连接下没有这个模型")
    patch = body.model_dump(exclude_unset=True)
    for field in provider_models.RUNTIME_FIELDS:
        if field in patch:
            setattr(model, field, patch[field])
    if "enabled" in patch and body.enabled is not None:
        model.enabled = body.enabled
    if "display_name" in patch:
        model.display_name = body.display_name or ""
    if "capability_ids" in patch:
        model.capability_ids = normalize_capability_ids(body.capability_ids) or []
    db.commit()
    return _model_out(model, _catalog_entries(profile))


@router.delete("/settings/providers/{profile_id}/models/{model_id:path}", status_code=204)
def delete_provider_model(profile_id: str, model_id: str, db: DbSession, user: CurrentUser) -> Response:
    """移除一行。目录里仍有的模型移除后会回到"未配置"状态(还能再加回来),
    手填的则彻底消失 —— 它本来就只存在于这一行里。"""
    ensure_instance_admin(db, user, "credentials")
    model = provider_models.get_model(db, profile_id, model_id)
    if model is not None:
        db.delete(model)
        db.commit()
    return Response(status_code=204)


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


def _network_out(row: NetworkConfig) -> NetworkConfigOut:
    return NetworkConfigOut(
        proxy_url=row.proxy_url,
        no_proxy=row.no_proxy,
        effective_no_proxy=effective_no_proxy(row.no_proxy),
    )


@router.get("/settings/network", response_model=NetworkConfigOut)
def get_network_config(db: DbSession, user: CurrentUser) -> NetworkConfigOut:
    ensure_instance_admin(db, user, "credentials")
    return _network_out(get_network(db))


@router.put("/settings/network", response_model=NetworkConfigOut)
def update_network_config(body: NetworkConfigUpdate, db: DbSession, user: CurrentUser) -> NetworkConfigOut:
    """改出站代理。立刻对本进程生效;sidecar 是每次新起的进程,下一次调用就带上新设置。

    内嵌浏览器由 Electron 侧自己拉取(桌面端启动时和改动后各取一次)——主进程与后端是两个
    进程,共享不了环境变量,只能各自读同一份配置。
    """
    ensure_instance_admin(db, user, "credentials")
    row = get_network(db)
    patch = body.model_dump(exclude_unset=True)
    if "proxy_url" in patch and body.proxy_url is not None:
        row.proxy_url = body.proxy_url.strip()
    if "no_proxy" in patch and body.no_proxy is not None:
        row.no_proxy = body.no_proxy.strip()
    db.commit()
    db.refresh(row)
    apply_to_process(row.proxy_url, row.no_proxy)
    logger.info("outbound proxy %s", row.proxy_url or "(direct)")
    return _network_out(row)


@router.get("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def get_ai_runtime(db: DbSession, user: CurrentUser) -> AiRuntimeConfigOut:
    row = db.get(AiRuntimeConfig, "default")
    return AiRuntimeConfigOut(max_retries=row.max_retries if row is not None else 3)


@router.put("/settings/ai-runtime", response_model=AiRuntimeConfigOut)
def set_ai_runtime(body: AiRuntimeConfigUpdate, db: DbSession, user: CurrentUser) -> AiRuntimeConfigOut:
    """AI 供应商瞬断/限流时的最大重试次数。**对所有 AI 出站调用生效** ——
    对话、生图、生视频、语音、向量化都走同一个带重试的传输层(domain/ai_retry)。"""
    ensure_instance_admin(db, user, "credentials")
    row = db.get(AiRuntimeConfig, "default")
    if row is None:
        row = AiRuntimeConfig(id="default")
        db.add(row)
    row.max_retries = body.max_retries
    db.commit()
    # 推进进程内状态:调用点散在十几个适配器里,其中不少拿不到 db 会话。
    # 与出站代理(domain/network.apply_to_process)同一套做法,改完即时生效、不必重启。
    set_max_retries(row.max_retries)
    return AiRuntimeConfigOut(max_retries=row.max_retries)
