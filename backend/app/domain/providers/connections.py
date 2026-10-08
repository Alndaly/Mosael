"""用户自己配的供应商连接:建、改、删,以及它在**某个人**眼里的样子。

连接(`ProviderProfile`)归建它的人;表单上的字段按供应商预设(`provider_presets`)分三处落:
端点、区域一类落在连接上,密的落在**填表那个人自己**的钥匙上(`provider_credentials`),
「模型」那一格落成一行模型(`provider_models`)。这张映射此前写在设置路由里,和 HTTP 混在一起。

插件实例对应的那条连接不在这里建 —— 它只是生成领域指向插件实例的把手,见
`providers.adopt_plugin_connection`。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import ProviderCredential, ProviderProfile
from app.domain.providers import credentials as provider_credentials
from app.domain.providers import models as provider_models
from app.domain.providers.auth import read_credential, refresh_recently_failed
from app.domain.providers.plugin_vendor import package_of
from app.domain.providers.presets import ProviderField, provider_definition
from app.domain.providers.quota import is_expired, supports_quota
from app.domain.providers.selection import normalize_auth_type, pi_provider_id


class ConnectionConfigError(LocalizedError, ValueError):
    """连接自己的必填字段(端点、区域一类)没填。api 回 422。"""


def create_connection(
    db: Session,
    *,
    owner_user_id: str,
    name: str,
    vendor: str,
    auth_type: str | None,
    config: dict[str, str],
    copy_credentials_from: ProviderProfile | None = None,
) -> ProviderProfile:
    """建一条**他自己的**连接。表单里填的密钥落成填表这个人的钥匙,不是连接上的一列。

    `copy_credentials_from`:同一把 Key 要配到另一能力的独立连接时,密钥从他自己的另一条连接
    直接拷过来,不经前端往返(设置接口对密钥只回打码提示,前端本就拿不到)。显式填了的照样优先。
    **调用方负责确认那条连接是他自己的** —— 否则这就是一条读到别人钥匙的路。

    **只建认得的那几家**(预设里有的)。此前 `vendor` 填什么都收:接口直调(智能体、脚本、旧客户端)能写进一条没有能力、
    没有端点、永远用不了的连接,还出现在列表里(SEC-14)。插件的连接不走这里(由插件实例建)。
    """
    if provider_definition(vendor) is None:
        raise ConnectionConfigError("providerErr_unknownVendor", vendor=vendor)
    incoming = dict(config)
    if copy_credentials_from is not None:
        source_key = provider_credentials.get(db, copy_credentials_from.id, owner_user_id)
        for spec in _field_specs(vendor):
            if spec.secret and not incoming.get(spec.key, "").strip():
                copied = _read_field(db, copy_credentials_from, spec, source_key)
                if copied:
                    incoming[spec.key] = copied
    profile = ProviderProfile(
        name=name,
        vendor=vendor,
        owner_user_id=owner_user_id,
        auth_type=normalize_auth_type(vendor, auth_type),
    )
    db.add(profile)
    db.flush()
    credential = provider_credentials.upsert(db, profile.id, owner_user_id)
    _apply_config(db, profile, incoming, creating=True, credential=credential)
    _sync_model_row(db, profile, incoming)
    return profile


def update_connection(
    db: Session,
    profile: ProviderProfile,
    *,
    user_id: str,
    name: str | None = None,
    enabled: bool | None = None,
    auth_type: str | None = None,
    config: dict[str, str] | None = None,
) -> None:
    """改连接。`None` 的项不动;`config` 里的密字段落在 `user_id` 自己那把钥匙上。"""
    if name is not None:
        profile.name = name
    if enabled is not None:
        profile.enabled = enabled
    if auth_type is not None:
        _switch_auth_type(db, profile, normalize_auth_type(profile.vendor, auth_type), user_id)
    incoming = dict(config or {})
    if incoming:
        credential = provider_credentials.upsert(db, profile.id, user_id)
        _apply_config(db, profile, incoming, creating=False, credential=credential)
    db.flush()
    _sync_model_row(db, profile, incoming)


def _switch_auth_type(db: Session, profile: ProviderProfile, next_auth: str, user_id: str) -> None:
    """换鉴权方式时清掉另一侧的凭据:留着的那份既不会被用到,又会让「已登录」说谎。

    清的是**我自己**那把:别人的钥匙不该被改连接时顺手抹掉。
    """
    if next_auth == profile.auth_type:
        return
    profile.auth_type = next_auth
    mine = provider_credentials.get(db, profile.id, user_id)
    if mine is None:
        return
    if next_auth == "api_key":
        mine.oauth_credential = None
    else:
        mine.api_key = ""
    mine.credential_version = (mine.credential_version or 0) + 1


def delete_connection(db: Session, profile: ProviderProfile) -> None:
    """删连接。钥匙、模型行、参数组跟着外键级联删掉。"""
    db.delete(profile)


def describe_connection(db: Session, profile: ProviderProfile, user_id: str) -> dict[str, Any]:
    """一条连接在**某个人**眼里的样子:连接行本身之外,界面要的那几项(键名即出参字段名)。

    钥匙状态(尾四位、登没登录、过没过期)说的全都是**他自己**那把。此前这些字段读的是档案行上
    那唯一一把,于是所有人看到同一份 —— 而那把是谁的没人说得清。
    """
    credential = provider_credentials.get(db, profile.id, user_id)
    oauth_linked = bool(credential and credential.oauth_credential)
    return {
        # 连接出现在哪几个能力分区 = 它下面启用模型的能力 ∪ 供应商预设(见 profile_capabilities)。
        "capability_ids": provider_models.profile_capabilities(db, profile),
        "key_hint": provider_credentials.key_hint(credential),
        "is_mine": credential is not None,
        "plugin_package_id": (package_of(profile.vendor) or None) if profile.plugin_instance_id else None,
        "extra": _masked_extra(profile, credential),
        "config": _masked_config(db, profile, credential),
        # 令牌本身不下发,只说「登上了没有」—— 界面要的也只有这个。
        "oauth_linked": oauth_linked,
        "quota_supported": supports_quota(pi_provider_id(profile.vendor)),
        # **「过期」不等于「要你重新授权」。** 订阅计划的 access token 普遍只有几小时,刷新是协议
        # 里就有的一步,后台会自己做(见 provider_auth.refresh_expired_in_background)。只按
        # is_expired 报的话,任何人只要在过期窗口里打开设置页,就会看到一行红字说「需重新授权」
        # —— 而它几秒后自己就好了。过期**且**最近真的刷不动,才是需要人来处理的事。
        "oauth_expired": (
            oauth_linked and is_expired(read_credential(credential)) and refresh_recently_failed(profile.id)
        ),
    }


# ---------------- 表单字段 ↔ 存储 ----------------


def _field_specs(vendor: str) -> tuple[ProviderField, ...]:
    definition = provider_definition(vendor)
    return definition.fields if definition else ()


def _read_field(
    db: Session, profile: ProviderProfile, spec: ProviderField, credential: ProviderCredential | None = None
) -> str:
    """表单上的一个字段当前的值。

    密的那几个跟着**钥匙**走:`credential` 是读的那个人自己的那把,给 None 就当没配过 ——
    别人的钥匙在这里读不出来,连尾四位也读不出来。
    """
    if spec.storage == "api_key":
        return (credential.api_key if credential else "") or ""
    if spec.secret:
        return str((credential.secrets if credential else {}).get(spec.key) or "")
    if spec.storage == "base_url":
        return profile.base_url or ""
    if spec.storage == "default_model":
        # 这个表单项落在模型行上,不在连接上。读回来时取这条连接在它主能力下的模型 ——
        # 绝大多数连接只有一个模型,读到的就是用户当初填的那个。
        capabilities = provider_models.profile_capabilities(db, profile)
        return provider_models.model_id_for(db, profile, capabilities[0]) if capabilities else ""
    value = (profile.extra or {}).get(spec.key)
    return str(value) if value else ""


def _write_field(
    profile: ProviderProfile, spec: ProviderField, value: str, credential: ProviderCredential | None = None
) -> None:
    """写一个表单字段。密的落到**写的人自己**那把钥匙上,其余落到这条连接上。"""
    key = spec.key
    if spec.storage == "api_key":
        if credential is not None:
            credential.api_key = value
        return
    if spec.secret:
        if credential is not None:
            secrets = dict(credential.secrets or {})
            if value:
                secrets[key] = value
            else:
                secrets.pop(key, None)
            credential.secrets = secrets
        return
    if spec.storage == "base_url":
        profile.base_url = value
        return
    if spec.storage == "default_model":
        return  # 由 _sync_model_row 建成模型行(它需要 db)
    extra = dict(profile.extra or {})
    if value:
        extra[key] = value
    else:
        extra.pop(key, None)
    profile.extra = extra


def _apply_config(
    db: Session,
    profile: ProviderProfile,
    incoming: dict[str, str],
    *,
    creating: bool,
    credential: ProviderCredential | None,
) -> None:
    """把表单值折进这条连接;密的那几个折进 `credential`(写的人自己那把)。"""
    if creating:
        definition = provider_definition(profile.vendor)
        profile.base_url = definition.base_url if definition else ""
        profile.extra = {}

    specs = _field_specs(profile.vendor)
    for spec in specs:
        if not spec.key:
            continue
        raw_value = incoming.get(spec.key)
        if raw_value is None:
            if creating and spec.default:
                _write_field(profile, spec, spec.default, credential)
            continue
        value = str(raw_value or "").strip()
        if value:
            _write_field(profile, spec, value, credential)
        elif spec.secret and not creating:
            continue  # 改连接时密字段留空 = 不动(界面上只有打码提示,填不回原值)
        else:
            _write_field(profile, spec, spec.default if creating else "", credential)

    def submitted(spec: ProviderField) -> str:
        """校验用的值。「模型」那一格落成的是模型行,而模型行在校验**之后**才建 ——
        拿"读回来的模型"去判必填永远是空,新建连接会一律报缺少默认模型。"""
        if spec.storage == "default_model":
            return (incoming.get(spec.key) or spec.default).strip() or _read_field(db, profile, spec)
        return _read_field(db, profile, spec)

    # 必填只管**连接自己的**字段(端点、区域一类)。密钥类的必填由存钥匙那条路管:一条还没有
    # 任何人填过钥匙的连接是完全正常的状态 —— 每个人带自己的那把,建连接的人不必替所有人先填。
    missing = [spec.label for spec in specs if spec.required and not spec.secret and not submitted(spec).strip()]
    if missing:
        raise ConnectionConfigError("providerErr_missingRequiredConfig", fields=", ".join(missing))


def _sync_model_row(db: Session, profile: ProviderProfile, incoming: dict[str, str]) -> None:
    """表单里那个「模型」字段落成模型行。

    建连接时顺手填一个模型是常见流程,但它写进的是 provider_models 的一行,和后来在模型列表里
    加的那些完全平权。能力留空,由 effective_capabilities 按证据规则认(认不出的生成模型只当对话
    模型);用户想细分就去模型列表里改。
    """
    model_id = ""
    for spec in _field_specs(profile.vendor):
        if spec.storage == "default_model":
            model_id = (incoming.get(spec.key) or spec.default).strip()
            if model_id:
                break
    if not model_id:
        definition = provider_definition(profile.vendor)
        model_id = definition.default_model.strip() if definition else ""
    if model_id:
        provider_models.upsert(db, profile, model_id, source="manual")


def _masked_config(db: Session, profile: ProviderProfile, credential: ProviderCredential | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in _field_specs(profile.vendor):
        value = _read_field(db, profile, spec, credential)
        if spec.key and value:
            out[spec.key] = f"…{value[-4:]}" if spec.secret else value
    return out


def _masked_extra(profile: ProviderProfile, credential: ProviderCredential | None) -> dict[str, str]:
    """密的附加字段只以尾四位出门,标识类(App ID)原样回 —— 表单要把它显示回去,而 AK/SK 发到
    浏览器就等于把 api_key 从不序列化的理由作废了。

    读的是连接的非密附加配置 + **我自己**那把钥匙上的密字段;别人的密字段这里取不到。
    """
    stored = {**(profile.extra or {}), **((credential.secrets if credential else {}) or {})}
    secret_keys = {spec.key for spec in _field_specs(profile.vendor) if spec.storage == "extra" and spec.secret}
    out: dict[str, str] = {}
    for key, value in stored.items():
        text = str(value or "")
        if text:
            out[key] = f"…{text[-4:]}" if key in secret_keys else text
    return out
