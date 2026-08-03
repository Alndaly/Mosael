"""插件接口:包 → 实例 → 能力。

**包**是磁盘上的东西(扫描 / 卸载),**实例**是一次接入(配置 / 凭据 / 权限 / 启用),
**能力**是实例暴露出来的工具。三层各自一组端点,别处(智能体、工作流)只读 `/plugins/tools`。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    PluginCapabilityUpdate,
    PluginCredentialOut,
    PluginCredentialUpdate,
    PluginEnableRequest,
    PluginInstanceCreate,
    PluginInstanceOut,
    PluginInstanceUpdate,
    PluginInvocationOut,
    PluginInvokeRequest,
    PluginPackageOut,
    PluginPermissionGrantOut,
    PluginPermissionGrantUpdate,
    PluginToolOut,
)
from app.core.config import settings
from app.core.permissions import ensure_deployment_admin
from app.db.models import PluginInvocation, PluginPackage
from app.domain.plugins import PluginDomainError
from app.domain.plugins import instances as inst
from app.domain.plugins import install as installer
from app.domain.plugins import packages as pkg
from app.domain.plugins import tools as tools_domain
from app.domain.plugins.manifest import manifest_of

router = APIRouter(tags=["plugins"])


def _fail(exc: PluginDomainError, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


# --- 包 -----------------------------------------------------------------

@router.post("/plugins/scan", response_model=list[PluginPackageOut])
def scan_packages(db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_deployment_admin(db, user)
    try:
        installer.sync(db, settings.plugins_dir)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _packages(db)


@router.get("/plugins/dir")
def plugins_directory(user: CurrentUser) -> dict[str, str]:
    """插件目录的**真实绝对路径**,给前端的空态引导用。

    这条路径曾经写死在前端文案里(`~/.open-studio/plugins/`)。那是 POSIX 写法:Windows 上
    `~/` 对用户没有任何意义,照着找是找不到的。路径由谁算就由谁报。
    """
    return {"path": str(settings.plugins_dir)}


@router.get("/plugins", response_model=list[PluginPackageOut])
def list_packages(db: DbSession) -> list[dict]:
    return _packages(db)


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


def _packages(db: DbSession) -> list[dict]:
    out: list[dict] = []
    for package in db.scalars(select(PluginPackage).order_by(PluginPackage.name)):
        manifest = manifest_of(package)
        out.append(
            {
                "id": package.id,
                "name": package.name,
                "version": package.version,
                "kind": manifest.runtime.kind,
                "multiple": manifest.multiple,
                "permissions": manifest.permissions,
                "config_fields": [_field(f) for f in manifest.config],
                "credential_fields": [_field(f) for f in manifest.credentials],
                "instances": [_instance(db, i) for i in pkg.instances_of(db, package.id)],
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
    ensure_deployment_admin(db, user)
    try:
        instance = inst.create(db, package_id, body.config, body.name)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.patch("/plugins/instances/{instance_id}", response_model=PluginInstanceOut)
def update_instance(instance_id: str, body: PluginInstanceUpdate, db: DbSession, user: CurrentUser) -> dict:
    ensure_deployment_admin(db, user)
    try:
        instance = inst.get(db, instance_id)
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
    ensure_deployment_admin(db, user)
    try:
        db.delete(inst.get(db, instance_id))
        db.commit()
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.post("/plugins/instances/{instance_id}/refresh", response_model=PluginInstanceOut)
def refresh_instance_tools(instance_id: str, db: DbSession, user: CurrentUser) -> dict:
    """重新向 MCP 服务要工具清单。进程类实例直接原样返回。"""
    ensure_deployment_admin(db, user)
    try:
        instance = tools_domain.refresh_tools(db, inst.get(db, instance_id))
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.patch("/plugins/instances/{instance_id}/capabilities", response_model=PluginInstanceOut)
def update_capabilities(
    instance_id: str, body: PluginCapabilityUpdate, db: DbSession, user: CurrentUser
) -> dict:
    ensure_deployment_admin(db, user)
    try:
        instance = inst.get(db, instance_id)
        inst.set_exposed(db, instance, body.tools)
    except PluginDomainError as exc:
        raise _fail(exc) from exc
    return _instance(db, instance)


@router.get("/plugins/instances/{instance_id}/permissions", response_model=list[PluginPermissionGrantOut])
def list_instance_permissions(instance_id: str, db: DbSession, user: CurrentUser) -> list:
    ensure_deployment_admin(db, user)
    try:
        return inst.list_permissions(db, inst.get(db, instance_id))
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.patch("/plugins/instances/{instance_id}/permissions", response_model=list[PluginPermissionGrantOut])
def update_instance_permissions(
    instance_id: str, body: PluginPermissionGrantUpdate, db: DbSession, user: CurrentUser
) -> list:
    # 授权是提权路径:未门禁的调用方可以先授权再调用,两个请求就绕过了确认。
    ensure_deployment_admin(db, user)
    try:
        return inst.set_permissions(db, inst.get(db, instance_id), body.grants)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


@router.get("/plugins/instances/{instance_id}/credentials", response_model=list[PluginCredentialOut])
def list_instance_credentials(instance_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_deployment_admin(db, user)
    try:
        return inst.describe_credentials(db, inst.get(db, instance_id))
    except PluginDomainError as exc:
        raise _fail(exc, 404) from exc


@router.patch("/plugins/instances/{instance_id}/credentials", response_model=list[PluginCredentialOut])
def update_instance_credentials(
    instance_id: str, body: PluginCredentialUpdate, db: DbSession, user: CurrentUser
) -> list[dict]:
    ensure_deployment_admin(db, user)
    try:
        instance = inst.get(db, instance_id)
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
def list_exposed_tools(db: DbSession) -> list[dict]:
    """所有可用实例**暴露**的工具。智能体工具表与工作流节点面板读的就是这一份。"""
    return tools_domain.exposed(db)


@router.post("/plugins/instances/{instance_id}/tools/{tool_name}/invoke", response_model=PluginInvocationOut)
def invoke_tool(
    instance_id: str, tool_name: str, body: PluginInvokeRequest, db: DbSession, user: CurrentUser
) -> PluginInvocation:
    ensure_deployment_admin(db, user)
    try:
        return tools_domain.invoke(db, instance_id, tool_name, body.input)
    except PluginDomainError as exc:
        raise _fail(exc) from exc


# --- 调用记录 -----------------------------------------------------------

@router.get("/plugins/invocations", response_model=list[PluginInvocationOut])
def list_invocations(db: DbSession, user: CurrentUser, instance_id: str | None = None) -> list[PluginInvocation]:
    ensure_deployment_admin(db, user)
    stmt = select(PluginInvocation)
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    return list(db.scalars(stmt.order_by(PluginInvocation.created_at.desc())))


@router.delete("/plugins/invocations/{invocation_id}", status_code=204)
def delete_invocation(invocation_id: str, db: DbSession, user: CurrentUser) -> None:
    ensure_deployment_admin(db, user)
    obj = db.get(PluginInvocation, invocation_id)
    if obj is not None:
        db.delete(obj)
        db.commit()


@router.delete("/plugins/invocations", status_code=204)
def clear_invocations(db: DbSession, user: CurrentUser, instance_id: str | None = None) -> None:
    """清空调用记录;带 instance_id 只清该连接的。"""
    ensure_deployment_admin(db, user)
    stmt = select(PluginInvocation)
    if instance_id:
        stmt = stmt.where(PluginInvocation.instance_id == instance_id)
    for obj in db.scalars(stmt):
        db.delete(obj)
    db.commit()


# 旧的 PluginEnableRequest 仍被 schema 引用;实例的启用走 PATCH /plugins/instances/{id}。
__all__ = ["router", "PluginEnableRequest"]
