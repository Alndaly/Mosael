"""插件接口:包 → 实例 → 能力。

**包**是磁盘上的东西(扫描 / 卸载),**实例**是一次接入(配置 / 凭据 / 权限 / 启用),
**能力**是实例暴露出来的工具。三层各自一组端点,别处(智能体、工作流)只读 `/plugins/tools`。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    PluginOAuthCode,
    PluginCapabilityUpdate,
    PluginCredentialOut,
    PluginCredentialUpdate,
    PluginEnableRequest,
    PluginInstallPreview,
    PluginInstallRequest,
    PluginInstanceCreate,
    PluginInstanceOut,
    PluginInstanceUpdate,
    PluginInvocationOut,
    PluginInvokeRequest,
    PluginMarketEntry,
    PluginPackageOut,
    PluginPermissionGrantOut,
    PluginPermissionGrantUpdate,
    PluginToolOut,
)
from app.core.config import settings
from app.domain.permissions import ensure_deployment_admin
from app.db.models import PluginInstance, PluginInvocation, PluginPackage
from app.domain.plugins import PluginDomainError
from app.domain.plugins import instances as inst
from app.domain.plugins import install as installer
from app.domain.plugins import packages as pkg
from app.domain.plugins import registry as market
from app.domain.plugins import tools as tools_domain
from app.domain.plugins.manifest import manifest_of, text_of, web_url

router = APIRouter(tags=["plugins"])


def _fail(exc: PluginDomainError, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


# --- 包 -----------------------------------------------------------------

@router.post("/plugins/scan", response_model=list[PluginPackageOut])
def scan_packages(db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_deployment_admin(db, user)
    try:
        installer.sync(db, settings.plugins_dir, owner_user_id=user.id)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _packages(db, user)


#: 内置的市场索引。部署管理员可以在设置里换成自己那一份(DeploymentConfig.plugin_registry_url)。
DEFAULT_REGISTRY_URL = "https://mosael.com/plugins/registry.json"


def _registry_url(db: DbSession) -> str:
    from app.db.models import DeploymentConfig

    config = db.get(DeploymentConfig, "default")
    return (config.plugin_registry_url if config else "").strip() or DEFAULT_REGISTRY_URL


@router.get("/plugins/market", response_model=list[PluginMarketEntry])
def browse_market(db: DbSession, user: CurrentUser) -> list[PluginMarketEntry]:
    """市场里有什么。**要管理员** —— 看到的下一步就是装,而装是往这台机器上放代码。"""
    ensure_deployment_admin(db, user)
    try:
        entries = market.fetch_index(_registry_url(db))
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    installed = {row.id: row.version for row in db.scalars(select(PluginPackage))}
    return [
        PluginMarketEntry(
            **{key: str(entry.get(key, "")) for key in ("id", "version", "author", "homepage", "download")},
            #: 索引里的名字和简介照搬清单,而清单里它们可以是按语言分的对象 —— 在这儿定语言。
            name=text_of(entry.get("name")),
            description=text_of(entry.get("description")),
            permissions=[p for p in (entry.get("permissions") or []) if isinstance(p, str)],
            installed=entry["id"] in installed,
            installed_version=installed.get(entry["id"], ""),
        )
        for entry in entries
    ]


@router.post("/plugins/install/preview", response_model=PluginInstallPreview)
def preview_install(body: PluginInstallRequest, db: DbSession, user: CurrentUser) -> PluginInstallPreview:
    """下下来读一遍清单就扔 —— **让用户在装之前看见它要什么权限**。

    权限清单写在清单里,而清单在包里面,不下下来看不到。少了这一步,「安装」就是一个
    什么都不说的按钮,而它做的事是往这台机器上放一份会被执行的代码。
    """
    ensure_deployment_admin(db, user)
    try:
        raw = market.preview_from_url(body.url.strip())
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    existing = db.get(PluginPackage, str(raw.get("id") or ""))
    declared = (raw.get("tools") or {}).get("declare") if isinstance(raw.get("tools"), dict) else []
    return PluginInstallPreview(
        id=str(raw.get("id") or ""),
        name=text_of(raw.get("name")),
        version=str(raw.get("version") or ""),
        description=text_of((raw.get("skills") or [{}])[0].get("description")) if raw.get("skills") else "",
        permissions=[p for p in (raw.get("permissions") or []) if isinstance(p, str)],
        tools=[str(t.get("name")) for t in (declared or []) if isinstance(t, dict) and t.get("name")],
        #: 只取这一个字段,不跑整份 parse —— 这份清单还没装上,它可能是畸形的,而
        #: 「预览」正是用来看清楚它的那一步,不该被它自己打成 500。
        homepage=web_url(raw.get("homepage")),
        installed=existing is not None,
        installed_version=existing.version if existing else "",
    )


@router.post("/plugins/install", response_model=list[PluginPackageOut])
def install_from_url(body: PluginInstallRequest, db: DbSession, user: CurrentUser) -> list[dict]:
    """下下来装上,然后照常扫描一遍(建默认实例、对齐字段)。"""
    ensure_deployment_admin(db, user)
    try:
        market.install_from_url(body.url.strip(), settings.plugins_dir, overwrite=body.overwrite)
        installer.sync(db, settings.plugins_dir, owner_user_id=user.id)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _packages(db, user)


@router.get("/plugins/dir")
def plugins_directory(user: CurrentUser) -> dict[str, str]:
    """插件目录的**真实绝对路径**,给前端的空态引导用。

    这条路径曾经写死在前端文案里(`~/.mosael/plugins/`)。那是 POSIX 写法:Windows 上
    `~/` 对用户没有任何意义,照着找是找不到的。路径由谁算就由谁报。
    """
    return {"path": str(settings.plugins_dir)}


@router.get("/plugins", response_model=list[PluginPackageOut])
def list_packages(db: DbSession, user: CurrentUser) -> list[dict]:
    return _packages(db, user)


def my_instance(db: DbSession, instance_id: str, user: CurrentUser) -> PluginInstance:
    """**我自己接的**那个,不是就 404。

    接入归人(见 db.models.PluginInstance)。"别人接的"和"不存在"对他是同一件事 —— 回 403 等于
    告诉他这个 id 有效。归属判定只此一处:每个路由各写一遍的话,漏掉任何一处都不会报错,
    只会让那条路径能读到别人的第三方凭据。
    """
    instance = db.get(PluginInstance, instance_id)
    if instance is None or instance.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="插件接入不存在")
    return instance


def _my_instance_ids(db: DbSession, user: CurrentUser) -> list[str]:
    return list(db.scalars(select(PluginInstance.id).where(PluginInstance.owner_user_id == user.id)))


def _packages(db: DbSession, user: CurrentUser) -> list[dict]:
    """装了哪些包 + **我自己**接的那些实例。

    包是这台机器的事实,人人看得到(否则他不知道有什么可接);实例是他自己的接入,别人的一个
    都不该出现 —— 此前这里不做过滤,新账号一进插件页就看到管理员接好的一排。
    """
    out: list[dict] = []
    for package in db.scalars(select(PluginPackage).order_by(PluginPackage.name)):
        manifest = manifest_of(package)
        out.append(
            {
                "id": package.id,
                #: 名字从清单现取,不取库里那一列 —— 那一列是装的时候定的,装的人是什么语言
                #: 就一直是什么语言;清单里若写了多语言,这里才跟得上看的人。
                "name": manifest.name,
                "version": package.version,
                "kind": manifest.runtime.kind,
                "multiple": manifest.multiple,
                "permissions": manifest.permissions,
                "homepage": manifest.homepage,
                "config_fields": [_field(f) for f in manifest.config],
                "credential_fields": [_field(f) for f in manifest.credentials],
                #: 声明了 OAuth 就给一个「去授权」的入口,不必手抄令牌(见 domain/plugins/oauth)。
                #: 声明不全的当没声明 —— 半个声明会长出一个点了必然失败的按钮。
                "oauth": manifest.oauth is not None,
                "instances": [
                    _instance(db, i)
                    for i in pkg.instances_of(db, package.id)
                    if i.owner_user_id == user.id
                ],
            }
        )
    return out


def _field(spec) -> dict:
    return {
        "key": spec.key,
        "label": spec.label,
        "type": spec.type,
        "help": spec.help,
        "required": spec.required,
        "secret": spec.secret,
        "options": spec.options,
        "default": spec.default,
    }


def _instance(db: DbSession, instance) -> dict:
    chosen = inst.exposed_tools(db, instance.id)
    return {
        "id": instance.id,
        "package_id": instance.package_id,
        "name": instance.name,
        "enabled": instance.enabled,
        "config": instance.config or {},
        "blocked_reason": inst.blocked_reason(db, instance),
        "tools": [{**tool, "exposed": tool["name"] in chosen} for tool in tools_domain.all_tools(db, instance)],
    }


# --- 实例 ---------------------------------------------------------------

@router.post("/plugins/{package_id}/instances", response_model=PluginInstanceOut)
def create_instance(package_id: str, body: PluginInstanceCreate, db: DbSession, user: CurrentUser) -> dict:
    """接一个**我自己的**。不要求部署管理员:他自己的账号、他自己的额度。

    没有归属判定可做(还没有这个接入)—— 建出来的就归他,这一行本身就是那道闸。
    """
    try:
        instance = inst.create(db, package_id, body.config, body.name, owner_user_id=user.id)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.patch("/plugins/instances/{instance_id}", response_model=PluginInstanceOut)
def update_instance(instance_id: str, body: PluginInstanceUpdate, db: DbSession, user: CurrentUser) -> dict:
    try:
        instance = my_instance(db, instance_id, user)
        if body.name is not None:
            inst.rename(db, instance, body.name)
        if body.config is not None:
            inst.set_config(db, instance, body.config)
        if body.enabled is not None:
            inst.set_enabled(db, instance, body.enabled)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.delete("/plugins/instances/{instance_id}", status_code=204)
def delete_instance(instance_id: str, db: DbSession, user: CurrentUser) -> None:
    try:
        db.delete(my_instance(db, instance_id, user))
        db.commit()
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.post("/plugins/instances/{instance_id}/refresh", response_model=PluginInstanceOut)
def refresh_instance_tools(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """重新向 MCP 服务要工具清单。进程类实例直接原样返回。"""
    try:
        instance = tools_domain.refresh_tools(db, my_instance(db, instance_id, user))
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.patch("/plugins/instances/{instance_id}/capabilities", response_model=PluginInstanceOut)
def update_capabilities(
    instance_id: str, body: PluginCapabilityUpdate, db: DbSession, user: CurrentUser
) -> dict:
    try:
        instance = my_instance(db, instance_id, user)
        inst.set_exposed(db, instance, body.tools)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.get("/plugins/instances/{instance_id}/permissions", response_model=list[PluginPermissionGrantOut])
def list_instance_permissions(instance_id: str, db: DbSession, user: CurrentUser) -> list:
    try:
        return inst.list_permissions(db, my_instance(db, instance_id, user))
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.patch("/plugins/instances/{instance_id}/permissions", response_model=list[PluginPermissionGrantOut])
def update_instance_permissions(
    instance_id: str, body: PluginPermissionGrantUpdate, db: DbSession, user: CurrentUser
) -> list:
    # 授权是提权路径:未门禁的调用方可以先授权再调用,两个请求就绕过了确认。
    try:
        return inst.set_permissions(db, my_instance(db, instance_id, user), body.grants)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


@router.get("/plugins/instances/{instance_id}/credentials", response_model=list[PluginCredentialOut])
def list_instance_credentials(instance_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    try:
        return inst.describe_credentials(db, my_instance(db, instance_id, user))
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.patch("/plugins/instances/{instance_id}/credentials", response_model=list[PluginCredentialOut])
def update_instance_credentials(
    instance_id: str, body: PluginCredentialUpdate, db: DbSession, user: CurrentUser
) -> list[dict]:
    try:
        instance = my_instance(db, instance_id, user)
        inst.set_credentials(db, instance, body.values)
        # 凭据是连上服务的前提,填完顺手重拉一次清单 —— 否则用户填完 key 还要再找一个
        # 「刷新」按钮点一下,而中间那段时间插件看起来像是坏的。
        try:
            tools_domain.refresh_tools(db, instance)
        except PluginDomainError:
            pass
        return inst.describe_credentials(db, instance)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


# --- 能力 ---------------------------------------------------------------

@router.get("/plugins/tools", response_model=list[PluginToolOut])
def list_exposed_tools(db: DbSession, user: CurrentUser) -> list[dict]:
    """所有可用实例**暴露**的工具。智能体工具表与工作流节点面板读的就是这一份。"""
    return tools_domain.exposed(db, user.id)


@router.post("/plugins/instances/{instance_id}/tools/{tool_name}/invoke", response_model=PluginInvocationOut)
def invoke_tool(
    instance_id: str, tool_name: str, body: PluginInvokeRequest, db: DbSession, user: CurrentUser
) -> PluginInvocation:
    my_instance(db, instance_id, user)  # 归属判定,和这个接入上其余操作同一道门
    try:
        return tools_domain.invoke(db, instance_id, tool_name, body.input)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


# --- 调用记录 -----------------------------------------------------------

@router.get("/plugins/invocations", response_model=list[PluginInvocationOut])
def list_invocations(db: DbSession, user: CurrentUser, instance_id: str | None = None) -> list[PluginInvocation]:
    """**我自己接的那些**的调用记录。

    记录里带着每次调用的 input/output —— 别人的请求参数和返回内容,没有任何理由出现在我这儿。
    此前这里不做过滤,因为那时接入本来就是所有人共用的一份。
    """
    stmt = select(PluginInvocation).where(PluginInvocation.instance_id.in_(_my_instance_ids(db, user)))
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    return list(db.scalars(stmt.order_by(PluginInvocation.created_at.desc())))


@router.delete("/plugins/invocations/{invocation_id}", status_code=204)
def delete_invocation(invocation_id: str, db: DbSession, user: CurrentUser) -> None:
    obj = db.get(PluginInvocation, invocation_id)
    if obj is not None:
        my_instance(db, obj.instance_id, user)  # 别人的记录删不得,也不该知道它存在
        db.delete(obj)
        db.commit()


@router.delete("/plugins/invocations", status_code=204)
def clear_invocations(db: DbSession, user: CurrentUser, instance_id: str | None = None) -> None:
    """清空**我自己**的调用记录;带 instance_id 只清该接入的。"""
    if instance_id:
        my_instance(db, instance_id, user)
    stmt = select(PluginInvocation).where(PluginInvocation.instance_id.in_(_my_instance_ids(db, user)))
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    for obj in db.scalars(stmt):
        db.delete(obj)
    db.commit()


# 旧的 PluginEnableRequest 仍被 schema 引用;实例的启用走 PATCH /plugins/instances/{id}。
__all__ = ["router", "PluginEnableRequest"]


# --- 卸载 ---------------------------------------------------------------
#
# **必须声明在最后。** `/plugins/{package_id}` 是个吃通配的路径,而 FastAPI 按声明顺序匹配 ——
# 它在上面时会把 `DELETE /plugins/invocations` 一并吃掉,当成"卸载一个叫 invocations 的包",
# 于是清空调用记录这件事从来就没成功过(管理员来也是一句 "Plugin not found")。
# 两条路由都要求部署管理员的年代看不出来:两边都 403/404,像是权限不够。

@router.delete("/plugins/{package_id}", status_code=204)
def uninstall_package(package_id: str, db: DbSession, user: CurrentUser) -> None:
    """卸载:删掉插件目录,连同它的实例、凭据、授权、调用记录。

    **连目录一起删**,否则下一次扫描又把它装回来 —— 用户看到的是"我删了它怎么又回来了"。
    """
    ensure_deployment_admin(db, user)
    try:
        pkg.uninstall(db, package_id, settings.plugins_dir)
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.get("/plugins/instances/{instance_id}/oauth")
def plugin_oauth_start(instance_id: str, db: DbSession, user: CurrentUser) -> dict[str, str]:
    """拿授权链接。**只是拼一个 URL**,这一步不碰网络也不写任何东西。

    用户点开它、在对方站点上登录并同意,然后把授权码贴回来(见下面的 complete)。
    多这一次粘贴,换来的是这条通路上没有任何可伪造的输入 —— 详见 domain/plugins/oauth
    里那段"为什么不用 mosael:// 接回调"。
    """
    from app.domain.plugins import oauth as plugin_oauth

    instance = my_instance(db, instance_id, user)
    manifest = inst.manifest_for(db, instance)
    try:
        spec = plugin_oauth.spec_of(manifest)
        url = plugin_oauth.authorize_url(spec, inst.credential_values(db, instance.id))
    except plugin_oauth.PluginOAuthError as exc:
        # 422:是"还差点什么"(没声明 oauth、没填 AppKey),不是服务端故障。
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"authorize_url": url, "redirect_uri": spec.redirect_uri}


@router.post("/plugins/instances/{instance_id}/oauth", response_model=list[PluginCredentialOut])
def plugin_oauth_complete(
    instance_id: str, body: PluginOAuthCode, db: DbSession, user: CurrentUser
) -> list[dict]:
    """拿授权码换令牌,写回插件声明的那几个凭据键。

    **只写对方真的回了的字段**(见 credentials_from_token):刷新时常常只回 access_token,
    把缺失当空串写回去会抹掉已有的 refresh_token —— 而那一份丢了要重新走一遍授权。
    """
    from app.core import http_retry
    from app.domain.plugins import oauth as plugin_oauth

    instance = my_instance(db, instance_id, user)
    manifest = inst.manifest_for(db, instance)
    try:
        spec = plugin_oauth.spec_of(manifest)
        stored = inst.credential_values(db, instance.id)
        payload = plugin_oauth.token_request(spec, stored, body.code)
        # 走统一的重试传输层:令牌端点一样会限流,而"刚授权完就失败"最让人摸不着头脑。
        with http_retry.RetryingClient(timeout=30) as client:
            response = client.post(spec.token_url, data=payload)
        response.raise_for_status()
        values = plugin_oauth.credentials_from_token(spec, response.json())
    except plugin_oauth.PluginOAuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 换令牌失败是结果,不是服务端故障
        raise HTTPException(status_code=422, detail=f"换令牌失败:{str(exc)[:200]}") from exc
    inst.set_credentials(db, instance, values)
    try:
        tools_domain.refresh_tools(db, instance)
    except PluginDomainError:
        pass
    return inst.describe_credentials(db, instance)
