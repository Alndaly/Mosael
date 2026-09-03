from __future__ import annotations

import threading
import time
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.domain.permissions import ensure_deployment_admin
from app.domain.agent.login import (
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
    ProviderCredentialIn,
    ProviderCredentialOut,
    ProviderProfileOut,
    ProviderProfileUpdate,
    VendorFieldOut,
    VendorPresetOut,
)
from app.core.config import settings as settings_config
from app.db.models import (
    AiRuntimeConfig,
    NetworkConfig,
    ProviderCredential,
    ProviderModel,
    ProviderPricingRule,
    ProviderProfile,
    new_id,
)
from app.domain import provider_credentials
from app.domain.provider_credentials import ResolvedConnection
from app.domain.provider_defaults import DEFAULTABLE_CAPABILITIES, set_default
from app.domain.network import apply_to_process, effective_no_proxy, get_config as get_network
from app.ai.sidecar.adapters import AdapterError, refresh_oauth_credential
from app.domain.agent.host import mint_tool_token
from app.domain import provider_models
from app.core.http_retry import set_max_retries
from app.domain.provider_quota import QuotaUnavailable, fetch_quota, is_expired, supports_quota
from app.domain import provider_health
from app.domain.provider_auth import acquire_lease, commit_credential, read_credential
from app.domain.provider_credentials import is_keyless
from app.domain.provider_presets import ProviderField, provider_definition, provider_definitions
from app.domain.providers import (
    pi_provider_id,
    capability_ids_for_vendor,
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

def _profile_out(db: DbSession, profile: ProviderProfile, user: CurrentUser) -> ProviderProfileOut:
    """一条连接在**某个人**眼里的样子。

    `user` 是必填的:钥匙状态(尾四位、登没登录、过没过期)说的全都是**他自己**那把。此前这些
    字段读的是档案行上那唯一一把,于是所有人看到同一份 —— 而那把是谁的没人说得清。

    端点地址不再需要遮:连接归人(见 db.models.ProviderProfile),他能看到的连接全是自己的。
    上一轮为了挡住"别人的私有部署地址印在他的列表里"加过一层按角色遮蔽 —— 那是打补丁,而且
    它会让一个普通成员看不到**自己那条**连接的地址。根因是那条连接本来就不该出现在他的列表里。
    """
    out = ProviderProfileOut.model_validate(profile)
    # 连接对外提供的能力 = 它下面所有启用模型能力的并集(没有模型行时回落 vendor 预设)。
    out.capability_ids = provider_models.profile_capabilities(db, profile)
    credential = provider_credentials.get(db, profile.id, user.id)
    out.key_hint = provider_credentials.key_hint(credential)
    out.is_mine = credential is not None
    out.needs_key = not is_keyless(profile.vendor)
    out.extra = _masked_extra(profile, credential)
    out.config = _masked_config(db, profile, credential)
    # 令牌本身不下发,只说「登上了没有」——UI 需要的也只有这个。
    out.oauth_linked = bool(credential and credential.oauth_credential)
    out.quota_supported = supports_quota(pi_provider_id(profile.vendor))
    # **「过期」不等于「要你重新授权」。** 订阅计划的 access token 普遍只有几小时,刷新是协议
    # 里就有的一步,后台会自己做(见 _auto_refresh_expired)。只按 is_expired 报的话,任何人
    # 只要在过期窗口里打开设置页,就会看到一行红字说「令牌刷新失败 · 需重新授权」——
    # 而它几秒后自己就好了。前端那句注释("走到这里说明后端已经替它刷过且没刷动")描述的是
    # 意图,这里才把它兑现:过期**且**最近真的刷不动,才是需要人来处理的事。
    out.oauth_expired = (
        out.oauth_linked
        and is_expired(read_credential(credential))
        and refresh_recently_failed(profile.id)
    )
    return out


def _field_specs(vendor: str) -> tuple[ProviderField, ...]:
    definition = provider_definition(vendor)
    return definition.fields if definition else ()


def _read_config_field(
    db: DbSession, profile: ProviderProfile, spec: ProviderField, credential: ProviderCredential | None = None
) -> str:
    """表单上的一个字段当前的值。

    密的那几个跟着**钥匙**走(见 domain/provider_credentials):`credential` 是读的那个人自己的
    那把,给 None 就当没配过 —— 别人的钥匙在这里读不出来,连尾四位也读不出来。
    """
    storage = spec.storage
    key = spec.key
    if storage == "api_key":
        return (credential.api_key if credential else "") or ""
    if spec.secret:
        return str((credential.secrets if credential else {}).get(key) or "")
    if storage == "base_url":
        return profile.base_url or ""
    if storage == "default_model":
        # 这个表单项现在落到模型行,不再存在档案上。读回来时取这条连接在它主能力下的模型 ——
        # 绝大多数连接只有一个模型,读到的就是用户当初填的那个。
        capabilities = provider_models.profile_capabilities(db, profile)
        return provider_models.model_id_for(db, profile, capabilities[0]) if capabilities else ""
    value = (profile.extra or {}).get(key)
    return str(value) if value else ""


def _write_config_field(
    profile: ProviderProfile, spec: ProviderField, value: str, credential: ProviderCredential | None = None
) -> None:
    """写一个表单字段。密的落到**写的人自己**那把钥匙上,其余落到这条连接上。"""
    storage = spec.storage
    key = spec.key
    if storage == "api_key":
        if credential is not None:
            credential.api_key = value
        return
    if spec.secret:
        if credential is not None:
            credential.secrets = {**(credential.secrets or {}), key: value} if value else {
                k: v for k, v in (credential.secrets or {}).items() if k != key
            }
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


def _masked_config(
    db: DbSession, profile: ProviderProfile, credential: ProviderCredential | None = None
) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in _field_specs(profile.vendor):
        key = spec.key
        value = _read_config_field(db, profile, spec, credential)
        if not key or not value:
            continue
        out[key] = f"…{value[-4:]}" if spec.secret else value
    return out


def _masked_extra(profile: ProviderProfile, credential: ProviderCredential | None = None) -> dict[str, str]:
    """Secret extras leave the server only as a hint; identifiers come back in full.

    An App ID is not a secret and the form needs to show it back, but an AK/SK is — sending
    those to the browser would undo the reason api_key is never serialised either.
    """
    # 连接的非密附加配置 + **我自己**那把钥匙上的密字段。别人的密字段这里取不到。
    stored = {**(profile.extra or {}), **((credential.secrets if credential else {}) or {})}
    secret_keys = {
        spec.key for spec in _field_specs(profile.vendor) if spec.storage == "extra" and spec.secret
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
        spec.key for spec in _field_specs(profile.vendor) if spec.storage == "extra" and spec.secret
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


def _apply_profile_config(
    db: DbSession,
    profile: ProviderProfile,
    incoming: dict[str, str],
    *,
    creating: bool,
    credential: ProviderCredential | None = None,
) -> None:
    """把表单值折进这条连接;密的那几个折进 `credential`(写的人自己那把)。"""
    definition = provider_definition(profile.vendor)
    if creating:
        profile.base_url = definition.base_url if definition else ""
        profile.extra = {}

    specs = _field_specs(profile.vendor)
    for spec in specs:
        key = spec.key
        if not key:
            continue
        raw_value = incoming.get(key)
        default_value = spec.default
        if raw_value is None:
            if creating and default_value:
                _write_config_field(profile, spec, credential=credential, value=default_value)
            continue

        value = str(raw_value or "").strip()
        if value:
            _write_config_field(profile, spec, credential=credential, value=value)
            continue

        if spec.secret and not creating:
            continue
        if default_value and creating:
            _write_config_field(profile, spec, credential=credential, value=default_value)
        else:
            _write_config_field(profile, spec, credential=credential, value="")

    def _submitted(spec: ProviderField) -> str:
        """校验用的值。default_model 这类字段落成的是模型行,而模型行在校验**之后**才建 ——
        拿"读回来的模型"去判必填永远是空,新建档案会一律报缺少默认模型。"""
        key = spec.key
        if spec.storage == "default_model":
            return (incoming.get(key) or spec.default).strip() or _read_config_field(
                db, profile, spec
            )
        return _read_config_field(db, profile, spec)

    # 必填只管**连接自己的**字段(端点、区域一类)。密钥类的必填由存钥匙那条路管:
    # 一条还没有任何人填过钥匙的连接是完全正常的状态 —— 每个人带自己的那把(见
    # domain/provider_credentials),建连接的人不必替所有人先填一个。
    missing = [
        spec.label
        for spec in specs
        if spec.required and not spec.secret and not _submitted(spec).strip()
    ]
    if missing:
        raise HTTPException(status_code=422, detail=f"缺少必要配置: {', '.join(missing)}")


@router.get("/settings/provider-vendors", response_model=list[VendorPresetOut])
def list_vendor_presets(user: CurrentUser) -> list[VendorPresetOut]:
    return [
        VendorPresetOut(
            vendor=definition.vendor,
            label=definition.label,
            capability_ids=list(definition.capability_ids),
            base_url=definition.base_url,
            default_model=definition.default_model,
            capabilities=definition.capabilities,
            fields=[VendorFieldOut(**vars(field)) for field in definition.fields],
            auth=list(definition.auth_types),
        )
        for definition in provider_definitions()
    ]


#: 刷新失败后多久才再试一次。失败通常不会因为再试而变好(refresh token 被吊销、账号在别处
#: 登出),而档案列表是设置页最常被拉的那个接口 —— 没有冷却就会变成每次进页面都起一次
#: node 去撞同一堵墙,页面还跟着卡。
_REFRESH_COOLDOWN_SECONDS = 300.0
_refresh_failed_at: dict[str, float] = {}


def refresh_recently_failed(profile_id: str) -> bool:
    """这条连接最近一次自动刷新令牌失败了没有。

    进程级内存:重启后是空的,于是重启后第一次拉列表会说「已授权」,哪怕它其实刷不动 ——
    下一次就对了。这个方向是**有意选的**:把"还不知道"说成"已授权"只会晚一次发现,
    而把它说成"需重新授权"是在没坏的时候喊坏,后者用户已经撞上了。
    """
    failed_at = _refresh_failed_at.get(profile_id)
    return failed_at is not None and time.monotonic() - failed_at < _REFRESH_COOLDOWN_SECONDS


def _auto_refresh_expired(db: DbSession, user: CurrentUser, profiles) -> None:
    """过期就去刷一次 —— **在后台**,不占着这次请求。

    **过期本身不是一个需要用户知道的状态**:订阅计划的 access token 普遍只有几小时,刷新是协议
    里就有的一步。此前只有对话路径和查额度会触发刷新,于是"隔夜再打开设置页"必然看到一行已过期
    —— 而它其实只要被用到就会自己好。

    **但它不能挡在列表前面。** 刷新是:起一个 Node 子进程(pi sidecar)→ 向那家供应商发一次
    网络请求 → 最长等 60 秒;而且每条过期连接串着来。断网或那家挂掉时,一件本地的纯读的事
    (告诉我我配了哪些连接)被一件远程的可选的事拖到几十秒 —— 用户看到的是设置页一直
    「正在连接后端…」,而日志里只有一行 fetch failed。

    判据:**这个接口要回答的问题,不需要出网就能回答。** 所以先把列表给他,刷新在后台跑,
    下一次拉列表时状态自己就对了。刷不动才让 oauth_expired 保持 True —— 那时是真的要重新授权。
    """
    stale = [
        (profile, row)
        for profile, row in profiles
        if profile.auth_type == "oauth" and row is not None and row.oauth_credential
    ]
    if not stale:
        return
    # 令牌在这里铸:后台线程拿不到这次请求的身份,而铸令牌要 db+user。
    token = mint_tool_token(db, user)
    pending = [
        (profile.id, profile.name, profile.vendor, credential)
        for profile, row in stale
        if (credential := read_credential(row)) is not None and is_expired(credential)
    ]
    for profile, row in stale:
        credential = read_credential(row)
        if credential is not None and not is_expired(credential):
            _refresh_failed_at.pop(profile.id, None)
    if not pending:
        return
    threading.Thread(target=_refresh_in_background, args=(token, pending), daemon=True).start()


def _refresh_in_background(token: str, pending: list[tuple[str, str, str, dict]]) -> None:
    """后台把过期的订阅令牌刷一遍。失败只记日志 —— 它本来就是"顺手做的事"。"""
    now = time.monotonic()
    for profile_id, name, vendor, credential in pending:
        if refresh_recently_failed(profile_id):
            continue
        try:
            refresh_oauth_credential(
                api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
                token=token,
                pi_provider=pi_provider_id(vendor) or "",
                profile_id=profile_id,
                credential=credential,
            )
        except AdapterError as exc:
            logger.warning("刷新 %s 的订阅令牌失败:%s", name, exc)
            _refresh_failed_at[profile_id] = now
            continue
        _refresh_failed_at.pop(profile_id, None)


@router.put("/settings/providers/{profile_id}/credential", response_model=ProviderCredentialOut)
def put_my_credential(
    profile_id: str, body: ProviderCredentialIn, db: DbSession, user: CurrentUser
) -> ProviderCredentialOut:
    """填**我自己**在这条连接上的钥匙。

    不要求部署管理员:连接与钥匙都归当前用户，只是端点配置和秘密/OAuth 状态分别保存、分别更新。
    """
    profile = _require_profile(db, profile_id, user)
    credential = provider_credentials.upsert(
        db,
        profile.id,
        user.id,
        api_key=(body.api_key or "").strip() if body.api_key is not None else None,
        secrets={k: v for k, v in (body.secrets or {}).items() if v.strip()} or None,
    )
    db.commit()
    db.refresh(credential)
    return ProviderCredentialOut(
        profile_id=profile.id,
        key_hint=provider_credentials.key_hint(credential),
        is_mine=True,
    )


@router.delete("/settings/providers/{profile_id}/credential", status_code=204)
def delete_my_credential(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    """撤回我自己的钥匙。**连接不动** —— 它不是我的。"""
    _require_profile(db, profile_id, user)
    provider_credentials.forget(db, profile_id, user.id)
    db.commit()
    return Response(status_code=204)


@router.get("/settings/providers", response_model=list[ProviderProfileOut])
def list_provider_profiles(db: DbSession, user: CurrentUser) -> list[ProviderProfileOut]:
    # **只给他自己的**。连接归人(见 db.models.ProviderProfile):此前这里不做任何过滤,
    # 于是新账号一进设置页就看到八条别人建的连接,每条底下一行「未配置你的密钥」。
    profiles = db.scalars(
        select(ProviderProfile)
        .where(ProviderProfile.owner_user_id == user.id)
        .order_by(ProviderProfile.created_at)
    ).all()
    # 自动续期只碰**我自己**那把钥匙 —— 过期的是谁的,谁登录的时候才刷得动。
    _auto_refresh_expired(db, user, [(p, provider_credentials.get(db, p.id, user.id)) for p in profiles])
    return [_profile_out(db, profile, user) for profile in profiles]


def _sync_model_row(db: DbSession, profile: ProviderProfile, incoming: dict[str, str]) -> None:
    """表单里那个「模型」字段落成模型行。

    档案上不再有 default_model —— 那是"一档案一模型"时代的字段。表单项保留是因为建连接时
    顺手填一个模型确实是常见流程,但它写进的是 provider_models 的一行,和后来在模型列表里
    加的那些完全平权。

    能力留空,由 effective_capabilities 回落 vendor 预设;用户想细分就去模型列表里改。
    """
    definition = provider_definition(profile.vendor)
    specs = [spec for spec in _field_specs(profile.vendor) if spec.storage == "default_model"]
    model_id = ""
    for spec in specs:
        key = spec.key
        model_id = (incoming.get(key) or spec.default).strip()
        if model_id:
            break
    if not model_id:
        model_id = definition.default_model.strip() if definition else ""
    if not model_id:
        return
    provider_models.upsert(db, profile, model_id, source="manual")


@router.post("/settings/providers", response_model=ProviderProfileOut)
def create_provider_profile(body: ProviderProfileCreate, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    """建一条**我自己的**连接。

    不再要求部署管理员:这是他自己的连接、他自己的钥匙、他自己的账单。要管理员才建得了的年代,
    普通成员只能看着别人的连接干瞪眼 —— 看得见、用不了、也建不了自己的。
    """
    profile = ProviderProfile(
        name=body.name,
        vendor=body.vendor,
        owner_user_id=user.id,
        auth_type=normalize_auth_type(body.vendor, body.auth_type),
    )
    # 服务端凭据复制:同一把 Key 要配到另一能力的独立档案时,密钥从既有档案
    # 直接拷进新行,不经前端往返(设置接口对密钥只回打码提示,前端本就拿不到)。
    # 先注入 secret 字段,再走常规配置应用 —— 显式传入的值仍可覆盖,必填校验共用。
    incoming = _config_from_body(body)
    if body.copy_credentials_from:
        # 只能从**自己的**连接复制密钥 —— 否则这就是一条读到别人钥匙的路。
        source = _require_profile(db, body.copy_credentials_from, user)
        for spec in _field_specs(body.vendor):
            if not spec.secret:
                continue
            key = spec.key
            if incoming.get(key, "").strip():
                continue  # 显式提供的密钥优先
            copied = _read_config_field(db, source, spec, provider_credentials.get(db, source.id, user.id))
            if copied:
                incoming[key] = copied
    db.add(profile)
    db.flush()
    # 表单里填的密钥落成**填表这个人**的钥匙,而不是连接上的一列。管理员建连接时顺手填的
    # 那把因此是他自己的 —— 别人各配各的。
    credential = provider_credentials.upsert(db, profile.id, user.id)
    _apply_profile_config(db, profile, incoming, creating=True, credential=credential)
    _sync_model_row(db, profile, incoming)
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile, user)


@router.patch("/settings/providers/{profile_id}", response_model=ProviderProfileOut)
def update_provider_profile(
    profile_id: str, body: ProviderProfileUpdate, db: DbSession, user: CurrentUser
) -> ProviderProfileOut:
    profile = _require_profile(db, profile_id, user)
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
            # 切换鉴权方式清掉另一侧的凭据 —— 留着的那份既不会被用到,又会让「已登录」说谎。
            # 清的是**我自己**那把:别人的钥匙不该被管理员改连接时顺手抹掉。
            mine = provider_credentials.get(db, profile.id, user.id)
            if mine is not None:
                if next_auth == "api_key":
                    mine.oauth_credential = None
                else:
                    mine.api_key = ""
                mine.credential_version = (mine.credential_version or 0) + 1
    incoming = _config_from_body(body)
    if incoming:
        _apply_profile_config(
            db, profile, incoming, creating=False,
            credential=provider_credentials.upsert(db, profile.id, user.id),
        )
    db.flush()
    _sync_model_row(db, profile, incoming)
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile, user)


def _require_profile(db: DbSession, profile_id: str, user: CurrentUser) -> ProviderProfile:
    """**我自己那条**连接,不是就 404。

    连接归人(见 db.models.ProviderProfile)。"别人的连接"和"不存在的连接"对他是同一件事 ——
    回 403 等于告诉他这个 id 有效,而他连它存不存在都不该知道。

    归属判定只此一处:每个路由各写一遍 `db.get(ProviderProfile, id)` 的话,漏掉任何一处都不会
    报错,只会让那条路径能读到、改到别人的东西。
    """
    profile = db.get(ProviderProfile, profile_id)
    if profile is None or profile.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return profile


def _oauth_profile(db: DbSession, profile_id: str, user: CurrentUser) -> ProviderProfile:
    profile = _require_profile(db, profile_id, user)
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


def _store_login_catalog(db: DbSession, profile: ProviderProfile, session, user: CurrentUser) -> None:
    """登录成功后把该账号的模型目录落库,并在没有默认模型时先挑一个。

    不挑的话用户回到设置页只会看到一个空的模型选择器,而「登录成功但用不了」比登录失败更费解。
    """
    if session.status != "done" or not session.models:
        return
    # 目录是**这次登录**的结果 —— 两个人的订阅档位可以不一样,所以它跟着钥匙走。
    provider_credentials.upsert(db, profile.id, user.id).model_catalog = session.models
    # 登录带回目录后,若这条连接一个模型行都没有,先把第一个建上 ——
    # 否则「登录成功但用不了」,比登录失败更费解。
    if not provider_models.list_models(db, profile.id):
        first = str(session.models[0].get("id", "")).strip()
        if first:
            provider_models.upsert(db, profile, first, source="catalog")
    db.commit()


@router.post("/settings/providers/{profile_id}/oauth/login", response_model=OAuthLoginOut)
def start_oauth_login(profile_id: str, db: DbSession, user: CurrentUser) -> OAuthLoginOut:
    """发起订阅计划的授权登录 —— 登的是**自己**的账号。

    这里不再要求部署管理员:订阅计划(Claude Pro/Max、Kimi Code)是按人计费的,一个部署里
    每个人都该能挂自己的。连接怎么配仍然是管理员的事,那是另一回事。
    """
    profile = _oauth_profile(db, profile_id, user)
    from app.domain.agent.host import mint_tool_token

    try:
        session = start_login(
            login_id=new_id(),
            profile_id=profile.id,
            pi_provider=pi_provider_id(profile.vendor),
            api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
            token=mint_tool_token(db, user),
            credential=read_credential(provider_credentials.get(db, profile.id, user.id)),
        )
    except LoginError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _login_out(session)


@router.get("/settings/providers/{profile_id}/oauth/login/{login_id}", response_model=OAuthLoginOut)
def poll_oauth_login(profile_id: str, login_id: str, db: DbSession, user: CurrentUser) -> OAuthLoginOut:
    profile = _oauth_profile(db, profile_id, user)
    session = get_login_session(login_id)
    if session is None or session.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="登录会话已结束")
    _store_login_catalog(db, profile, session, user)
    return _login_out(session)


@router.post("/settings/providers/{profile_id}/oauth/login/{login_id}/answer", response_model=OAuthLoginOut)
def answer_oauth_login(
    profile_id: str, login_id: str, body: OAuthAnswerIn, db: DbSession, user: CurrentUser
) -> OAuthLoginOut:
    _oauth_profile(db, profile_id, user)
    session = get_login_session(login_id)
    if session is None or session.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="登录会话已结束")
    if not answer_login(login_id, body.prompt_id, body.answer):
        raise HTTPException(status_code=409, detail="这一步已经不在等待作答了")
    return _login_out(session)


@router.delete("/settings/providers/{profile_id}/oauth/login/{login_id}", status_code=204)
def cancel_oauth_login(profile_id: str, login_id: str, db: DbSession, user: CurrentUser) -> None:
    _oauth_profile(db, profile_id, user)
    cancel_login(login_id)


@router.get("/settings/providers/{profile_id}/health", response_model=ProviderHealthOut)
def probe_provider_health(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderHealthOut:
    """探一次这条连接通不通、往返多久。

    **只在被问到时探**,不做后台轮询:探针会真的打到用户的端点上(本地 ComfyUI、云端 /models),
    定时轮询等于替用户持续产生请求 —— 而"它现在通不通"这个问题只在他看着这一页时才有意义。
    """
    profile = _require_profile(db, profile_id, user)
    result = provider_health.probe(_resolved_or_bare(db, profile, user))
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
    profile = _oauth_profile(db, profile_id, user)
    pi_provider = pi_provider_id(profile.vendor)
    if not supports_quota(pi_provider):
        return ProviderQuotaOut(supported=False)
    mine = provider_credentials.get(db, profile.id, user.id)
    credential = read_credential(mine)
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
            db.refresh(mine) if mine is not None else None
            credential = read_credential(provider_credentials.get(db, profile.id, user.id))
        except AdapterError as exc:
            return ProviderQuotaOut(supported=True, error=f"令牌刷新失败:{exc}")
    try:
        snapshot = fetch_quota(pi_provider, credential)
    except QuotaUnavailable as exc:
        return ProviderQuotaOut(supported=True, error=str(exc))
    return ProviderQuotaOut(supported=True, **snapshot)


@router.delete("/settings/providers/{profile_id}/oauth", response_model=ProviderProfileOut)
def logout_oauth_provider(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    """解除**我自己**在这条连接上的订阅登录。登出是应用侧动作,跑对话的 sidecar 无权做。"""
    profile = _oauth_profile(db, profile_id, user)
    lease = acquire_lease(profile.id, user.id)
    commit_credential(db, profile.id, user.id, lease, None)
    mine = provider_credentials.get(db, profile.id, user.id)
    if mine is not None:
        mine.model_catalog = None
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile, user)


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


@router.get("/settings/provider-defaults", response_model=list[ProviderDefaultOut])
def list_provider_defaults(db: DbSession, user: CurrentUser) -> list[ProviderDefaultOut]:
    """**我**在每种能力下的默认供应商+模型。我没设过的就是空 —— 没有部署兜底那一档。"""
    from app.domain.provider_defaults import get_row

    out: list[ProviderDefaultOut] = []
    for capability in DEFAULTABLE_CAPABILITIES:
        row = get_row(db, capability, user.id)
        # 默认只存一处(指向模型行),连接与模型名从那一行推导出来给界面。
        model = db.get(ProviderModel, row.provider_model_id) if row and row.provider_model_id else None
        out.append(
            ProviderDefaultOut(
                capability=capability,
                provider_profile_id=model.provider_profile_id if model else None,
                model=model.model_id if model else "",
                # 恒真:能拿到行就说明是我自己设的(get_row 只查我这一条)。字段留着是因为
                # 前端还在读它,而且它现在表达的是"这一格有没有被我设过"。
                is_mine=row is not None,
            )
        )
    return out


@router.get("/settings/capability-models/{capability}", response_model=list[CapabilityModelOut])
def list_capability_models(
    capability: str,
    db: DbSession,
    user: CurrentUser,
    surface: Literal["all", "agent", "direct", "gateway", "automation"] = "all",
) -> list[CapabilityModelOut]:
    """某能力下所有可用模型,跨连接。**任何登录用户都读得到** —— 挡住它等于让人闭着眼睛
    选自己的默认模型(见 tests/test_who_owns_each_setting.py)。

    界面直接列它,而不是"先选供应商再选模型" —— 后者是模型还不是实体时的形状,逼着用户
    先知道"这个模型在哪条连接下",而那恰恰是他不关心的事。
    """
    if capability not in DEFAULTABLE_CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    return [
        CapabilityModelOut(
            provider_profile_id=model.provider_profile_id,
            provider_name=model.profile.name if model.profile is not None else "",
            model=model.model_id,
            display_name=model.display_name or "",
            # 思考能力跟着模型走:有的完全不思考,有的只能开/关,有的才分档。
            # 界面据此决定给几个选项 —— 给一个点了没用的开关,比没有这个开关更坏。
            reasoning=model.reasoning,
            reasoning_effort=model.reasoning_effort,
        )
        for model in provider_models.models_for_capability(db, capability, user.id, surface=surface)
    ]


@router.put("/settings/provider-defaults/{capability}", response_model=ProviderDefaultOut)
def set_provider_default(
    capability: str, body: ProviderDefaultUpdate, db: DbSession, user: CurrentUser
) -> ProviderDefaultOut:
    """设**我自己**在这项能力下的默认模型。**只有这一档。**

    不要求部署管理员:「我默认用哪个模型」是个人偏好,和钥匙一样(见 db.models.ProviderDefault)。
    曾经有过 `for_deployment` —— 写那一行 `owner_user_id=""` 当作"还没设过的人的起点" ——
    删掉了:替人做的选择必须是他自己做的(见 domain/provider_defaults.get_row)。
    """
    if capability not in DEFAULTABLE_CAPABILITIES:
        raise HTTPException(status_code=404, detail="未知能力")
    model = None
    model_id = body.model.strip()
    if body.provider_profile_id and model_id:
        profile = _require_profile(db, body.provider_profile_id, user)
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
    set_default(db, capability, model, owner_user_id=user.id)
    db.commit()
    return ProviderDefaultOut(
        capability=capability,
        provider_profile_id=model.provider_profile_id if model is not None else None,
        model=model.model_id if model is not None else "",
        is_mine=True,
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


def _resolved_or_bare(db: DbSession, profile: ProviderProfile, user: CurrentUser) -> ResolvedConnection:
    """这条连接 + 我的钥匙;没有钥匙时给一个不带钥匙的 —— 目录取不到就是空列表,
    而「还没填密钥」不该让整个模型页 500。

    我自己那一行即使还没有密钥也要用上:订阅登录会先把模型目录存进这一行,而**目录不是钥匙**
    —— 按"有没有密钥"把它跳过去,会让刚登录完的人看到一个空的模型选择器。
    """
    resolved = provider_credentials.resolve_connection(db, profile, user.id)
    if resolved is not None:
        return resolved
    mine = provider_credentials.get(db, profile.id, user.id)
    return ResolvedConnection(
        id=profile.id, name=profile.name, vendor=profile.vendor, base_url=profile.base_url or "",
        auth_type=profile.auth_type, enabled=profile.enabled, extra=dict(profile.extra or {}),
        model_catalog=mine.model_catalog if mine is not None else None,
    )


def _catalog_entries(profile: ResolvedConnection) -> dict[str, dict]:
    """该连接的**目录**(供应商说它有什么)。订阅计划的目录只有登录才知道(Copilot 随档位变、
    OpenRouter 有几百个),登录时由 pi 带回存下;API Key 档案现打 /models(带 TTL 缓存)。"""
    if profile.vendor == "comfyui":
        # ComfyUI 是工作流引擎,没有模型目录 —— 它的"目录"就是实例里保存的工作流。
        # 走同一个接缝而不是在前端分叉:这样「加入 / 启停 / 删除 / 设能力」整套交互
        # 对工作流原样成立,只有文案不同。连不上就返回空,和端点没模型是同一种表现。
        from app.ai.providers.adapters.comfyui.client import ComfyUIClient

        try:
            items = ComfyUIClient(profile.base_url or "http://127.0.0.1:8188").list_workflows()
        except Exception as exc:  # noqa: BLE001 — 连不上是常态(忘了启动),不该让设置页 500
            logger.info("ComfyUI 工作流列表获取失败(%s):%s", profile.base_url, exc)
            return {}
        return {str(item["path"]): {"context_window": None, "max_output_tokens": None} for item in items if item.get("path")}
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


def _is_known_model(vendor: str, model_id: str, catalog: dict[str, dict]) -> bool:
    """这个模型是不是"我们认得的"。

    「目录中已不存在」这个提示的本意是**预警**:曾经能用的模型从供应商目录里消失了(下架、
    改名),再点下去就会失败。判据原本只有一条 —— 在不在实时目录里。

    可实时目录读的是 OpenAI 兼容的 `/models`,而有些能力走供应商的原生端点、**从来就不在
    那份清单里**:百炼的万相视频就是这样。于是每一个从内置目录加进来的模型都挂着"已不存在",
    而它明明刚验证过能用(真机截图)。一个永远为真的警告等于没有警告 —— 更糟的是它会让用户
    去删一个好模型。

    所以内置目录也算数:它是**验证过的事实**,不是"端点当下报了什么"。
    """
    if model_id in catalog:
        return True
    from app.domain.generation import builtin_models_for

    return any(model_id in builtin_models_for(vendor, kind) for kind in ("image", "video"))


def _model_out(model, catalog: dict[str, dict], vendor: str = "") -> ProviderModelOut:
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
        in_catalog=_is_known_model(vendor or (model.profile.vendor if model.profile else ""), model.model_id, catalog),
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
    """这条连接下的模型:**已配置的行 + 实时目录 + 内置目录**。

    三者合并而不是二选一 —— 实时目录说端点现在有什么(会变),模型行说用户做过什么(不该被
    目录冲掉),内置目录补上**实时目录看不见的那些**。

    第三份不是可有可无的:实时目录读的是 OpenAI 兼容的 `/models`,而有些能力走供应商的原生
    端点、根本不在那份清单里 —— 百炼的万相视频就是这样(真机实测:那个接口对百炼只返回两个
    wan **图像**模型,一个视频模型都没有)。少了这一份,用户在设置里看不到、加不进来,于是
    生成页的下拉里那一家整个是空的,而他并不知道为什么。

    已配置的排在前面:那是用户实际在用的;其余可一键加入。
    """
    # 只读:任何登录用户都看得到这条连接下有哪些模型 —— 他要据此选自己的默认。
    profile = _require_profile(db, profile_id, user)
    catalog = _catalog_entries(_resolved_or_bare(db, profile, user))
    configured = provider_models.list_models(db, profile_id)
    rows = [_model_out(model, catalog, profile.vendor) for model in configured]
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
                # 和落库后 effective_capabilities 走同一条判据 —— 否则列表里显示的能力
                # 和加进去之后的能力对不上,而用户是照着列表做的决定。
                effective_capability_ids=(
                    provider_models.infer_capabilities(profile.vendor, model_id)
                    or capability_ids_for_vendor(profile.vendor)
                ),
            )
        )
        known.add(model_id)

    # 内置目录:走原生端点、不在 /models 里的那些。能力**按 kind 给准**,而不是套用 vendor
    # 的全集 —— 一个万相视频模型不该被声明成"对话 + 图像 + 视频 + 语音"。
    from app.domain.generation import builtin_models_for

    for kind in ("image", "video"):
        for model_id in builtin_models_for(profile.vendor, kind):
            if model_id in known:
                continue
            known.add(model_id)
            rows.append(
                ProviderModelOut(
                    id=model_id,
                    configured=False,
                    # 对界面来说它和目录项是一回事:没配过、可一键加入。区别只在"这份清单
                    # 是静态的",而那是实现细节,不是用户要分辨的东西。
                    in_catalog=True,
                    enabled=False,
                    context_window=None,
                    context_window_source="fallback",
                    max_output_tokens=None,
                    effective_capability_ids=[kind],
                )
            )
    return rows


@router.post("/settings/providers/{profile_id}/models", response_model=ProviderModelOut)
def add_provider_model(
    profile_id: str, body: ProviderModelUpdate, db: DbSession, user: CurrentUser
) -> ProviderModelOut:
    """把一个模型加进这条连接。目录里选的和手填的走同一条路 —— 区别只在 source,
    手填是为了私有部署与别名:目录查不到不等于不能用。"""
    profile = _require_profile(db, profile_id, user)
    model_id = (body.model_id or "").strip()
    if not model_id:
        raise HTTPException(status_code=422, detail="模型 id 不能为空")
    catalog = _catalog_entries(_resolved_or_bare(db, profile, user))
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
    return _model_out(model, catalog, profile.vendor)


@router.patch("/settings/providers/{profile_id}/models/{model_id:path}", response_model=ProviderModelOut)
def update_provider_model(
    profile_id: str, model_id: str, body: ProviderModelUpdate, db: DbSession, user: CurrentUser
) -> ProviderModelOut:
    """改一行。

    **model_id 必须用 :path 转换器**:模型 id 里带斜杠是常态(kimi/kimi-k2.7-code、
    MiniMax/MiniMax-M2.5、ZHIPU/GLM-5),而普通路径参数不跨 `/`,路由直接匹配不上 ——
    表现是删除/修改一律 404,而且只有那些带斜杠的模型才复现。
    运行时项传 null 即清除、回到跟随目录 —— 与"没传"是两回事,后者不动它。"""
    profile = _require_profile(db, profile_id, user)
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
    return _model_out(model, _catalog_entries(_resolved_or_bare(db, profile, user)), profile.vendor)


@router.delete("/settings/providers/{profile_id}/models/{model_id:path}", status_code=204)
def delete_provider_model(profile_id: str, model_id: str, db: DbSession, user: CurrentUser) -> Response:
    """移除一行。目录里仍有的模型移除后会回到"未配置"状态(还能再加回来),
    手填的则彻底消失 —— 它本来就只存在于这一行里。"""
    _require_profile(db, profile_id, user)  # 归属判定,和这条连接上其余操作同一道门
    model = provider_models.get_model(db, profile_id, model_id)
    if model is not None:
        db.delete(model)
        db.commit()
    return Response(status_code=204)


@router.delete("/settings/providers/{profile_id}", status_code=204)
def delete_provider_profile(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    profile = _require_profile(db, profile_id, user)
    if profile is not None:
        db.delete(profile)
        db.commit()
    return Response(status_code=204)





def _network_out(row: NetworkConfig) -> NetworkConfigOut:
    return NetworkConfigOut(
        proxy_url=row.proxy_url,
        no_proxy=row.no_proxy,
        effective_no_proxy=effective_no_proxy(row.no_proxy),
    )


@router.get("/settings/network", response_model=NetworkConfigOut)
def get_network_config(db: DbSession, user: CurrentUser) -> NetworkConfigOut:
    ensure_deployment_admin(db, user)
    return _network_out(get_network(db))


@router.put("/settings/network", response_model=NetworkConfigOut)
def update_network_config(body: NetworkConfigUpdate, db: DbSession, user: CurrentUser) -> NetworkConfigOut:
    """改出站代理。立刻对本进程生效;sidecar 是每次新起的进程,下一次调用就带上新设置。

    内嵌浏览器由 Electron 侧自己拉取(桌面端启动时和改动后各取一次)——主进程与后端是两个
    进程,共享不了环境变量,只能各自读同一份配置。
    """
    ensure_deployment_admin(db, user)
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
    ensure_deployment_admin(db, user)
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
