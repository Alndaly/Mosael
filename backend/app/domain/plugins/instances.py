"""插件**实例**:一次具体接入 = 包 + 配置 + 凭据 + 显示名 + 启用开关。

配置与凭据是同一种东西的两侧(`Field.secret`),差别只在控件和回显:凭据读出去是掩码,
把掩码原样交回来表示"这项没改"。它们一起参与 `${...}` 展开,一起注入插件进程的环境。

**为什么要有实例这一层**:一个包可以被接入多次。TikHub 一个包对应十几个平台端点,B站一个、
抖音一个,各有各的凭据和显示名。此前包和接入是同一行记录,于是"平台"只能是一个凭据,而包名
写死在 manifest 里 —— 用户配了 bilibili,面板上仍然写着「抖音」。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PluginCapability, PluginCredential, PluginInstance, PluginPackage, PluginPermissionGrant
from app.domain.plugins import host_capabilities
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import Field, Manifest, manifest_of, render_name
from app.core.i18n import tr

#: 掩码回显。前端把它原样发回来时表示"这项没改"。
MASK = "********"


def get(db: Session, instance_id: str) -> PluginInstance:
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        raise PluginDomainError("pluginErr_instanceNotFound")
    return instance


def manifest_for(db: Session, instance: PluginInstance) -> Manifest:
    package = db.get(PluginPackage, instance.package_id)
    if package is None:
        raise PluginDomainError("pluginErr_packageNotFound")
    return manifest_of(package)


def create(
    db: Session,
    package_id: str,
    config: dict[str, Any] | None = None,
    name: str = "",
    *,
    owner_user_id: str = "",
) -> PluginInstance:
    package = db.get(PluginPackage, package_id)
    if package is None:
        raise PluginDomainError("pluginErr_notFound")
    manifest = manifest_of(package)
    # 「只能有一个」是**对这个人**而言的:接入归人(见 db.models.PluginInstance),
    # 别人接过不该挡住我接我自己的那一个。
    existing = db.scalars(
        select(PluginInstance).where(
            PluginInstance.package_id == package_id, PluginInstance.owner_user_id == owner_user_id
        )
    ).all()
    if existing and not manifest.multiple:
        raise PluginDomainError("pluginErr_singleConnection", name=manifest.name)
    _check_json(manifest, config or {})
    merged = _fit_config(manifest, config or {})
    instance = PluginInstance(
        package_id=package_id,
        owner_user_id=owner_user_id,
        name=name.strip() or render_name(manifest, merged),
        enabled=False,
        config=merged,
        discovered_tools=[],
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    _sync_permissions(db, instance, manifest)
    host_capabilities.notify(db, instance, refresh=True)
    return instance


def reconcile_fields(db: Session, instance: PluginInstance, manifest: Manifest) -> None:
    """把存错地方的值搬回去 —— 一个字段从「凭据」改成「配置」(或反过来)时用。

    manifest 是作者写的,而作者会改主意:TikHub 的 platform 一开始是凭据(那时没有配置这个
    概念),现在是枚举配置。用户早就填过 bilibili,不该因为我们改了分类就得重填一遍 ——
    **重填是我们的问题,不是他的**。按 key 搬,搬完删掉原处那行。
    """
    config_keys = {spec.key for spec in manifest.config}
    if not config_keys:
        return
    moved: dict[str, Any] = {}
    for row in list(db.scalars(select(PluginCredential).where(PluginCredential.instance_id == instance.id))):
        if row.key in config_keys:
            moved[row.key] = row.value
            db.delete(row)
    if not moved:
        return
    instance.config = _fit_config(manifest, {**(instance.config or {}), **moved})
    if manifest.name_template:
        instance.name = render_name(manifest, instance.config)
    db.commit()


#: 下面几个会改实例的函数都带 `notify`:改完要不要通知替宿主做事的那一侧(见 host_capabilities)。
#: 默认通知;一次请求里连改几样的调用方(改名 + 改配置 + 启用)关掉逐个通知、最后统一通知一次 ——
#: 否则一个 ComfyUI 实例的一次保存会把服务器上的工作流清单拉三遍。


def rename(db: Session, instance: PluginInstance, name: str, *, notify: bool = True) -> PluginInstance:
    instance.name = name.strip() or instance.name
    db.commit()
    db.refresh(instance)
    if notify:
        host_capabilities.notify(db, instance, refresh=False)
    return instance


def set_enabled(db: Session, instance: PluginInstance, enabled: bool, *, notify: bool = True) -> PluginInstance:
    instance.enabled = enabled
    db.commit()
    if enabled:
        # MCP 实例启用时顺手拉一次工具清单:没有它,实例启用了但工具表是空的,而"为什么没
        # 工具"这个问题在界面上无处可答。失败不阻止启用 —— 常见原因是凭据还没填,而填凭据
        # 的入口正是启用之后那张卡片;卡在这里会变成死结。
        from app.domain.plugins.tools import refresh_tools

        try:
            refresh_tools(db, instance, notify=False)
        except PluginDomainError:
            pass
    db.refresh(instance)
    if notify:
        # 启用 = 它能做的事可能变了(刚能用上),停用 = 宿主那一侧要跟着停。
        host_capabilities.notify(db, instance, refresh=enabled)
    return instance


# --- 配置 ---------------------------------------------------------------

def _fit_config(manifest: Manifest, values: dict[str, Any]) -> dict[str, Any]:
    """只保留 manifest 声明过的键,顺带套默认值。声明先行:这张表不是通用键值库。"""
    out: dict[str, Any] = {}
    for spec in manifest.config:
        raw = values.get(spec.key, spec.default)
        out[spec.key] = _coerce(spec, raw)
    return out


def _coerce(spec: Field, raw: Any) -> Any:
    if spec.type == "boolean":
        return raw is True or str(raw).lower() in ("true", "1", "yes")
    if spec.type == "number":
        try:
            return float(raw) if str(raw).strip() else ""
        except (TypeError, ValueError):
            return ""
    value = str(raw or "")
    # 枚举收到不认识的值就退回空:一个填错的平台会让整条连接静默连到不存在的端点。
    if spec.type == "enum" and value and spec.options and value not in {o["value"] for o in spec.options}:
        return ""
    return value


def _check_json(manifest: Manifest, values: dict[str, Any]) -> None:
    """`type: "json"` 的配置项保存前必须能解析。**错在哪一行哪一列当场说** —— 存进去再让插件报一句
    「不是合法 JSON」,用户要从插件的一次失败里倒推是哪一格、哪个逗号。空的不查(没填 ≠ 填错)。"""
    for spec in manifest.config:
        if spec.type != "json" or spec.key not in values:
            continue
        text = str(values[spec.key] or "")
        if not text.strip():
            continue
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluginDomainError(
                "pluginErr_configNotJson", label=spec.label, line=exc.lineno, column=exc.colno, detail=exc.msg
            ) from exc


def set_config(
    db: Session, instance: PluginInstance, values: dict[str, Any], *, notify: bool = True
) -> PluginInstance:
    manifest = manifest_for(db, instance)
    allowed = {spec.key for spec in manifest.config}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise PluginDomainError("pluginErr_unknownConfig", keys=", ".join(unknown))
    _check_json(manifest, values)
    previous_name = render_name(manifest, instance.config or {})
    instance.config = _fit_config(manifest, {**(instance.config or {}), **values})
    # 名字跟着配置走 —— 除非用户改过它。判据是"当前名字正是上一份配置生成的那个"。
    if manifest.name_template and instance.name in (previous_name, "", manifest.name):
        instance.name = render_name(manifest, instance.config)
    db.commit()
    db.refresh(instance)
    if notify:
        # 配置变了(换了一台服务器)= 它能做的事可能变了,重新问一遍。
        host_capabilities.notify(db, instance, refresh=True)
    return instance


def missing_config(db: Session, instance: PluginInstance) -> list[str]:
    manifest = manifest_for(db, instance)
    config = instance.config or {}
    return [spec.label for spec in manifest.config if spec.required and not config.get(spec.key)]


# --- 凭据 ---------------------------------------------------------------

def credential_values(db: Session, instance_id: str) -> dict[str, str]:
    rows = db.scalars(select(PluginCredential).where(PluginCredential.instance_id == instance_id))
    return {row.key: row.value for row in rows}


def describe_credentials(db: Session, instance: PluginInstance) -> list[dict[str, Any]]:
    values = credential_values(db, instance.id)
    manifest = manifest_for(db, instance)
    out = []
    for spec in manifest.credentials:
        value = values.get(spec.key, "")
        out.append(
            {
                "key": spec.key,
                "label": spec.label,
                "help": spec.help,
                "secret": spec.secret,
                "required": spec.required,
                "filled": bool(value),
                "value": (MASK if value else "") if spec.secret else value,
            }
        )
    return out


def set_credentials(
    db: Session, instance: PluginInstance, values: dict[str, str], *, notify: bool = True
) -> None:
    manifest = manifest_for(db, instance)
    allowed = {spec.key for spec in manifest.credentials}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise PluginDomainError("pluginErr_unknownCredentials", keys=", ".join(unknown))
    for key, value in values.items():
        if value == MASK:
            continue  # 掩码原样回传 = 这项没改;用户改别的字段时不会把 key 洗成一串星号
        row = db.get(PluginCredential, {"instance_id": instance.id, "key": key})
        if row is None:
            db.add(PluginCredential(instance_id=instance.id, key=key, value=value))
        else:
            row.value = value
    db.commit()
    if notify:
        host_capabilities.notify(db, instance, refresh=True)


def missing_credentials(db: Session, instance: PluginInstance) -> list[str]:
    values = credential_values(db, instance.id)
    manifest = manifest_for(db, instance)
    return [spec.label for spec in manifest.credentials if spec.required and not values.get(spec.key)]


def secrets_for(db: Session, instance: PluginInstance) -> dict[str, str]:
    """`${...}` 展开与进程注入用的值:配置 + 已填的凭据,按声明的 key。"""
    merged = {key: str(value) for key, value in (instance.config or {}).items() if value not in (None, "")}
    merged.update({key: value for key, value in credential_values(db, instance.id).items() if value})
    return merged


def process_env(db: Session, instance: PluginInstance) -> dict[str, str]:
    """注入进程类插件子进程的环境变量。键大写 —— 环境变量的惯例,声明处不必写两遍。"""
    return {key.upper(): value for key, value in secrets_for(db, instance).items()}


# --- 权限 ---------------------------------------------------------------

def _sync_permissions(db: Session, instance: PluginInstance, manifest: Manifest) -> None:
    for permission in manifest.permissions:
        if db.get(PluginPermissionGrant, {"instance_id": instance.id, "permission": permission}) is None:
            db.add(PluginPermissionGrant(instance_id=instance.id, permission=permission, granted=False))
    db.commit()


def list_permissions(db: Session, instance: PluginInstance) -> list[PluginPermissionGrant]:
    _sync_permissions(db, instance, manifest_for(db, instance))
    return list(
        db.scalars(
            select(PluginPermissionGrant)
            .where(PluginPermissionGrant.instance_id == instance.id)
            .order_by(PluginPermissionGrant.permission)
        )
    )


def set_permissions(db: Session, instance: PluginInstance, grants: dict[str, bool]) -> list[PluginPermissionGrant]:
    manifest = manifest_for(db, instance)
    unknown = sorted(set(grants) - set(manifest.permissions))
    if unknown:
        raise PluginDomainError("pluginErr_unknownPermissions", keys=", ".join(unknown))
    _sync_permissions(db, instance, manifest)
    for permission, granted in grants.items():
        row = db.get(PluginPermissionGrant, {"instance_id": instance.id, "permission": permission})
        if row is not None:
            row.granted = granted
    db.commit()
    # 授权是「能不能用」的最后一道门:刚授全了就该去问它能做什么,撤了就该停。
    host_capabilities.notify(db, instance, refresh=True)
    return list_permissions(db, instance)


def permissions_granted(db: Session, instance: PluginInstance) -> bool:
    manifest = manifest_for(db, instance)
    if not manifest.permissions:
        return True
    grants = {
        row.permission: row.granted
        for row in db.scalars(select(PluginPermissionGrant).where(PluginPermissionGrant.instance_id == instance.id))
    }
    return all(grants.get(permission) is True for permission in manifest.permissions)


def blocked_reason(db: Session, instance: PluginInstance) -> str:
    """这个实例为什么还不能用。空串 = 可以用。

    把三道门(启用 / 配置 / 凭据 / 授权)收成一句话:界面和智能体报错都用它,免得同一件事
    在三处各写一句不一样的话。
    """
    if not instance.enabled:
        return tr("pluginBlocked_disabled")
    absent = missing_config(db, instance)
    if absent:
        return tr("pluginBlocked_missingConfig", names=tr("punct_listSep").join(absent))
    absent = missing_credentials(db, instance)
    if absent:
        return tr("pluginBlocked_missingCredentials", names=tr("punct_listSep").join(absent))
    if not permissions_granted(db, instance):
        return tr("pluginBlocked_permissionsPending")
    return ""


# --- 能力开关 -----------------------------------------------------------

def exposed_tools(db: Session, instance_id: str) -> set[str]:
    rows = db.scalars(
        select(PluginCapability).where(PluginCapability.instance_id == instance_id, PluginCapability.exposed.is_(True))
    )
    return {row.tool_name for row in rows}


def set_exposed(db: Session, instance: PluginInstance, choices: dict[str, bool]) -> None:
    for tool_name, exposed in choices.items():
        row = db.get(PluginCapability, {"instance_id": instance.id, "tool_name": tool_name})
        if row is None:
            db.add(PluginCapability(instance_id=instance.id, tool_name=tool_name, exposed=exposed))
        else:
            row.exposed = exposed
    db.commit()


def seed_capabilities(
    db: Session,
    instance: PluginInstance,
    manifest: Manifest,
    tool_names: list[str],
    *,
    recommended: set[str] | frozenset[str] = frozenset(),
) -> None:
    """给还没有记录的工具建一条:`expose: "all"` 全开,否则只开 manifest 推荐的那些。

    `recommended` 是清单之外、**运行时报出的**工具自己说的推荐(见 dynamic_tools)。
    默认关是有意的 —— 见 models.py 里 PluginCapability 的说明。
    """
    known = {
        row.tool_name
        for row in db.scalars(select(PluginCapability).where(PluginCapability.instance_id == instance.id))
    }
    recommended = set(manifest.recommended) | set(recommended)
    for name in tool_names:
        if name in known:
            continue
        db.add(
            PluginCapability(
                instance_id=instance.id,
                tool_name=name,
                exposed=manifest.expose == "all" or name in recommended,
            )
        )
    db.commit()


def set_capability_status(db: Session, instance: PluginInstance, capability: str, status: dict[str, Any]) -> None:
    """记下这个实例替宿主做 `capability` 那件事**上一次做得怎么样**(见 PluginInstance.capability_status)。

    整份换掉而不是就地改:JSON 列上的就地修改 ORM 看不见,会静默地不落库。
    """
    instance.capability_status = {**(instance.capability_status or {}), capability: dict(status)}
    db.commit()


__all__ = [
    "MASK",
    "blocked_reason",
    "create",
    "credential_values",
    "describe_credentials",
    "exposed_tools",
    "get",
    "list_permissions",
    "manifest_for",
    "missing_config",
    "missing_credentials",
    "permissions_granted",
    "process_env",
    "rename",
    "secrets_for",
    "seed_capabilities",
    "set_config",
    "set_credentials",
    "set_capability_status",
    "set_enabled",
    "set_exposed",
    "set_permissions",
]
