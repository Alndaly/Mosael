from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.ai.sidecar.adapters import AdapterError, refresh_oauth_credential
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    ProviderCredentialIn,
    ProviderCredentialOut,
    ProviderHealthOut,
    ProviderProfileCreate,
    ProviderProfileOut,
    ProviderProfileUpdate,
    VendorFieldOut,
    VendorPresetOut,
)
from app.core.config import settings as settings_config
from app.db.models import ProviderCredential, ProviderProfile
from app.domain import provider_credentials, provider_health, provider_models
from app.domain.agent.host import mint_tool_token
from app.domain.provider_auth import read_credential
from app.domain.provider_credentials import ResolvedConnection, is_keyless
from app.domain.provider_presets import ProviderField, provider_definition, provider_definitions
from app.domain.provider_quota import is_expired, supports_quota
from app.domain.providers import normalize_auth_type, pi_provider_id

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



@router.delete("/settings/providers/{profile_id}", status_code=204)
def delete_provider_profile(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    profile = _require_profile(db, profile_id, user)
    if profile is not None:
        db.delete(profile)
        db.commit()
    return Response(status_code=204)





