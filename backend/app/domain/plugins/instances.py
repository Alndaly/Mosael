"""插件**实例**:一次具体接入 = 包 + 配置 + 凭据 + 显示名 + 启用开关。

配置与凭据是同一种东西的两侧(`Field.secret`),差别只在控件和回显:凭据读出去是掩码,
把掩码原样交回来表示"这项没改"。它们一起参与 `${...}` 展开,一起注入插件进程的环境。

**为什么要有实例这一层**:一个包可以被接入多次。TikHub 一个包对应十几个平台端点,B站一个、
抖音一个,各有各的凭据和显示名。此前包和接入是同一行记录,于是"平台"只能是一个凭据,而包名
写死在 manifest 里 —— 用户配了 bilibili,面板上仍然写着「抖音」。
"""

from __future__ import annotations

import json
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.model_base import now
from app.db.models import PluginCapability, PluginCredential, PluginInstance, PluginPackage, PluginPermissionGrant
from app.domain.plugins import egress, host_capabilities, oauth as plugin_oauth, package_sources
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import TOOLS, Field, Manifest, manifest_of, render_name
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
    grant: Collection[str] = (),
    enabled: bool = False,
) -> PluginInstance:
    """新建一个连接:`add` 再 `commit_created`。"""
    return commit_created(db, add(db, package_id, config, name, owner_user_id=owner_user_id, grant=grant, enabled=enabled))


def add(
    db: Session,
    package_id: str,
    config: dict[str, Any] | None = None,
    name: str = "",
    *,
    owner_user_id: str = "",
    grant: Collection[str] = (),
    enabled: bool = False,
) -> PluginInstance:
    """建一个连接和它的授权记录,**只 flush、不提交、不通知**。同一次新建里还有别的要一起建时用它(本机服务的连接:那一行、
    端口、写进 `server_url` 的地址,见 local_services.create_connection),全做完再 `commit_created`;中途哪一步不成,调用方
    回滚,连接也不留下。

    `grant`:人在新建弹窗里看过、同意建好时一起授予的那几项权限,必须是清单里声明的。

    `enabled`:人在插件页「新建连接」里亲手建的是 True —— 建它就是要用它,还缺的权限、配置、凭据各自挡着(blocked_reason),
    补齐那一下它就能用,不再要人另外去拨「启用」(此前横幅说「授予之后就能用了」,授予完却还是停用的)。装插件时顺手建的
    默认连接照旧是停用的:装上不等于启用。"""
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
    unknown = sorted(set(grant) - set(manifest.permissions))
    if unknown:
        raise PluginDomainError("pluginErr_unknownPermissions", keys=", ".join(unknown))
    _check_json(manifest, config or {})
    merged = _fit_config(manifest, config or {})
    instance = PluginInstance(
        package_id=package_id,
        owner_user_id=owner_user_id,
        name=name.strip() or render_name(manifest, merged),
        enabled=enabled,
        config=merged,
        discovered_tools=[],
    )
    db.add(instance)
    db.flush()
    _seed_permissions(db, instance, manifest, granted=grant)
    return instance


def commit_created(db: Session, instance: PluginInstance) -> PluginInstance:
    """新建的连接落库,再通知替宿主做事的那一侧。**一定在提交之后通知**:那一侧要读到这一行,它对齐失败时还会回滚会话 ——
    没提交的话,回滚掉的是这个连接本身。"""
    db.commit()
    db.refresh(instance)
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
        _pull_tools(db, instance)
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


def write_config(db: Session, instance: PluginInstance, values: dict[str, Any]) -> Manifest:
    """改这个连接的配置,**只 flush**:清单声明过的键才收、JSON 那几格要能解析、名字跟着配置走。提交、重拉工具、通知归调用方
    (`set_config` 就是它加上这三样;本机服务写宿主分的地址时只要它,见 local_services.records)。交回清单。"""
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
    db.flush()
    return manifest


def set_config(
    db: Session, instance: PluginInstance, values: dict[str, Any], *, notify: bool = True
) -> PluginInstance:
    manifest = write_config(db, instance, values)
    db.commit()
    db.refresh(instance)
    if instance.enabled and manifest.is_mcp:
        # 换了一台 MCP 服务器,手里那份工具清单说的就是上一台 —— 和启用时一样顺手重拉。
        _pull_tools(db, instance)
    if notify:
        # 配置变了(换了一台服务器)= 它能做的事可能变了,重新问一遍。
        host_capabilities.notify(db, instance, refresh=True)
    return instance


def set_network(
    db: Session, instance: PluginInstance, mode: str, proxy_url: str = "", *, notify: bool = True
) -> PluginInstance:
    """这个连接往外连走哪条路:跟随 Mosael / 直连 / 走它自己的代理(见 egress)。

    和改配置一样顺手重拉一次:MCP 的工具清单、替宿主做事的那一侧(模型目录)此前可能正是因为路不通才空着。
    """
    instance.network_mode, instance.proxy_url = egress.normalize(mode, proxy_url)
    db.commit()
    db.refresh(instance)
    if instance.enabled and manifest_for(db, instance).is_mcp:
        _pull_tools(db, instance)
    if notify:
        host_capabilities.notify(db, instance, refresh=True)
    return instance


def set_package_sources(db: Session, instance: PluginInstance, choices: dict[str, str]) -> PluginInstance:
    """这个连接装包从哪个镜像拉(见 package_sources):只改给了的生态;空串 = 改回跟随「管理 → 下载源」。
    不用重拉工具清单 —— 镜像只在插件下次装依赖时才用到。"""
    overrides = dict(instance.package_sources or {})
    for source, choice in choices.items():
        normalized = package_sources.normalize(source, choice)
        if normalized:
            overrides[source] = normalized
        else:
            overrides.pop(source, None)
    #: 换一个新 dict 赋回去:JSON 列原地改,ORM 看不出它变了。提交交给入口层(路由的 Tx)。
    instance.package_sources = overrides
    db.flush()
    return instance


def _pull_tools(db: Session, instance: PluginInstance) -> None:
    """顺手拉一次工具清单。**失败不抛**:原因由 refresh_tools 记进 `capability_status["tools"]`,插件页照着说;
    缺配置、缺凭据那种由 blocked_reason 说。"""
    from app.domain.plugins.tools import refresh_tools

    try:
        refresh_tools(db, instance, notify=False)
    except PluginDomainError:
        pass


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
    written = set()
    for key, value in values.items():
        if value == MASK:
            continue  # 掩码原样回传 = 这项没改;用户改别的字段时不会把 key 洗成一串星号
        written.add(key)
        row = db.get(PluginCredential, {"instance_id": instance.id, "key": key})
        if row is None:
            db.add(PluginCredential(instance_id=instance.id, key=key, value=value))
        else:
            row.value = value
    # 授权写的那几格换了新值(重新授权、手动贴了新令牌、插件自己续出来的)= 上一次「对方不认」说的
    # 已经不是现在这份令牌了。
    if manifest.oauth is not None and written & set(manifest.oauth.stores.values()):
        instance.authorization_rejected_at = None
    db.commit()
    if notify:
        host_capabilities.notify(db, instance, refresh=True)


def missing_credentials(db: Session, instance: PluginInstance) -> list[str]:
    values = credential_values(db, instance.id)
    manifest = manifest_for(db, instance)
    return [spec.label for spec in manifest.credentials if spec.required and not values.get(spec.key)]


def secrets_for(db: Session, instance: PluginInstance) -> dict[str, str]:
    """`${...}` 展开与进程注入用的值:清单**现在**声明的配置和凭据里填了的那几项。

    只按声明的键取:插件更新后去掉的凭据键,那一行还在库里 —— 插件页照清单列凭据,看不到它、也删不掉;此前它照样每次注入
    插件进程(PLG-15)。配置写的时候就只收声明的键(_fit_config),老版本留下的照样在这里挡一道。"""
    manifest = manifest_for(db, instance)
    config_keys = {spec.key for spec in manifest.config}
    credential_keys = {spec.key for spec in manifest.credentials}
    merged = {key: str(value) for key, value in (instance.config or {}).items()
              if key in config_keys and value not in (None, "")}
    merged.update({key: value for key, value in credential_values(db, instance.id).items() if key in credential_keys and value})
    return merged


def process_env(db: Session, instance: PluginInstance) -> dict[str, str]:
    """注入进程类插件子进程的环境变量。键大写 —— 环境变量的惯例,声明处不必写两遍。"""
    return {key.upper(): value for key, value in secrets_for(db, instance).items()}


# --- 权限 ---------------------------------------------------------------

def _seed_permissions(db: Session, instance: PluginInstance, manifest: Manifest, *, granted: Collection[str] = ()) -> None:
    """清单声明的每一项权限都有一行:缺的补上,缺省没授予(`granted` 里的那几项建成授予)。只 flush。"""
    for permission in manifest.permissions:
        if db.get(PluginPermissionGrant, {"instance_id": instance.id, "permission": permission}) is None:
            db.add(PluginPermissionGrant(instance_id=instance.id, permission=permission, granted=permission in granted))
    db.flush()


def _sync_permissions(db: Session, instance: PluginInstance, manifest: Manifest) -> None:
    _seed_permissions(db, instance, manifest)
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


def _grants(db: Session, instance: PluginInstance) -> dict[str, bool]:
    return {
        row.permission: row.granted
        for row in db.scalars(select(PluginPermissionGrant).where(PluginPermissionGrant.instance_id == instance.id))
    }


def pending_permissions(db: Session, instance: PluginInstance) -> list[str]:
    """清单声明了、这个连接还没授予的权限,按清单里的先后。"""
    grants = _grants(db, instance)
    return [permission for permission in manifest_for(db, instance).permissions if grants.get(permission) is not True]


def permissions_added(db: Session, instance: PluginInstance) -> bool:
    """还缺的权限是不是**插件更新后多要的**:这个连接授予过清单里的别的权限(用过),只是新版多声明了几项。

    两种处境说的话不一样:刚接上的连接是「还没授予」;用得好好的连接升级后停了,要说清楚是插件多要了权限、
    之前授予的不受影响 —— 不然用户只看到「用不了」,以为插件坏了。
    """
    grants = _grants(db, instance)
    permissions = manifest_for(db, instance).permissions
    granted = [one for one in permissions if grants.get(one) is True]
    return bool(granted) and len(granted) < len(permissions)


def permissions_granted(db: Session, instance: PluginInstance) -> bool:
    return not pending_permissions(db, instance)


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
        # 缺的正好是授权会填的那几格:该说「还没授权」,而不是让人去找一格收起来的 Refresh Token。
        manifest = manifest_for(db, instance)
        if manifest.oauth is not None and set(absent) <= {
            one.label for one in plugin_oauth.fills(manifest.oauth, manifest.credentials)
        }:
            return tr("pluginBlocked_unauthorized")
        return tr("pluginBlocked_missingCredentials", names=tr("punct_listSep").join(absent))
    pending = pending_permissions(db, instance)
    if pending:
        names = tr("punct_listSep").join(pending)
        if permissions_added(db, instance):
            return tr("pluginBlocked_permissionsAdded", n=len(pending), names=names)
        return tr("pluginBlocked_permissionsPending", names=names)
    return ""


# --- 授权 ---------------------------------------------------------------

def authorization_state(db: Session, instance: PluginInstance) -> str:
    """声明了 `instance.oauth` 的连接授权到哪一步(见 oauth.authorization_state)。没声明的是空串。

    只看每一格**填没填**,令牌本身不出这个函数。
    """
    manifest = manifest_for(db, instance)
    if manifest.oauth is None:
        return ""
    filled = {key for key, value in credential_values(db, instance.id).items() if value}
    return plugin_oauth.authorization_state(
        manifest.oauth, manifest.credentials, filled, rejected=instance.authorization_rejected_at is not None
    )


def note_authorization(db: Session, instance: PluginInstance, *, rejected: bool) -> None:
    """记下一次调用对授权的说法:插件说对方不认了(`rejected`),或者一次调用成功了(令牌显然还有效)。

    不提交 —— 调用方(tools.invoke)随这次调用记录一起提交。没声明 oauth 的插件不记:它说了
    `reauthorize` 也没有「去授权」可以点,也就没有任何东西会把它清掉。
    """
    if manifest_for(db, instance).oauth is None:
        return
    if rejected:
        instance.authorization_rejected_at = now()
    elif instance.authorization_rejected_at is not None:
        instance.authorization_rejected_at = None


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
    db.flush()


def carry_capabilities(db: Session, instance: PluginInstance, renames: dict[str, str]) -> None:
    """工具改了名(一次性的改名,见 plugins.moves):新名字照旧名字的开关开 / 关 —— 那个开关是用户对「旧名字以前指的那件事」
    的选择,它现在叫新名字。旧名字的开关原样留着(旧名字另有所指,用户以前也开着它)。新名字已经有开关的不动。不提交。"""
    rows = {
        row.tool_name: row
        for row in db.scalars(select(PluginCapability).where(PluginCapability.instance_id == instance.id))
    }
    for source, target in renames.items():
        if source in rows and target not in rows:
            db.add(PluginCapability(instance_id=instance.id, tool_name=target, exposed=rows[source].exposed))
    db.flush()


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


def record_tool_list(db: Session, instance: PluginInstance, count: int, **extra: Any) -> None:
    """工具清单刷新成功:记下几件、什么时候,清掉上一次的错。

    `capability_status["tools"]` 这一格有两个写的人 —— 进程插件自报清单(dynamic_tools)、MCP 连接
    被问出清单(tools.refresh_tools)—— 插件页只读这一种形状,所以形状只在这里定一次。
    """
    set_capability_status(db, instance, TOOLS, {
        "tools": count, "refreshed_at": _stamp(), **extra, "error": "", "error_key": "", "error_params": {},
    })


def record_tool_list_failure(db: Session, instance: PluginInstance, exc: Exception) -> None:
    """工具清单没刷出来:原因记下来(插件页照着说),上一次成功的记录留着 —— 清单本身也还是上一份。"""
    from app.domain.jobs import blame

    previous = dict((instance.capability_status or {}).get(TOOLS) or {})
    set_capability_status(db, instance, TOOLS, {**previous, **blame(exc), "attempted_at": _stamp()})


def _stamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


__all__ = [
    "MASK",
    "add",
    "authorization_state",
    "blocked_reason",
    "commit_created",
    "create",
    "credential_values",
    "describe_credentials",
    "exposed_tools",
    "get",
    "list_permissions",
    "manifest_for",
    "missing_config",
    "missing_credentials",
    "note_authorization",
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
    "set_network",
    "set_permissions",
    "write_config",
]
