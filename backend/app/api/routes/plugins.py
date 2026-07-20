from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    PluginEnableRequest,
    PluginInvocationOut,
    PluginInvokeRequest,
    PluginOut,
    PluginPermissionGrantOut,
    PluginPermissionGrantUpdate,
    PluginToolOut,
)
from app.core.config import settings
from app.core.permissions import ensure_instance_admin
from app.db.models import Plugin, PluginInvocation, PluginPermissionGrant
from app.domain.plugins import (
    PluginDomainError,
    invoke_plugin_tool,
    list_enabled_plugin_tools,
    list_plugin_permission_grants,
    scan_plugins,
    set_plugin_enabled,
    set_plugin_permission_grants,
)

router = APIRouter(tags=["plugins"])


@router.post("/plugins/scan", response_model=list[PluginOut])
def scan_plugin_manifests(db: DbSession, user: CurrentUser) -> list[Plugin]:
    ensure_instance_admin(db, user, "edit")
    try:
        return scan_plugins(db, settings.plugins_dir)
    except PluginDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plugins", response_model=list[PluginOut])
def list_plugins(db: DbSession) -> list[Plugin]:
    stmt = select(Plugin).order_by(Plugin.name)
    return list(db.scalars(stmt))


@router.patch("/plugins/{plugin_id}", response_model=PluginOut)
def update_plugin(plugin_id: str, body: PluginEnableRequest, db: DbSession, user: CurrentUser) -> Plugin:
    ensure_instance_admin(db, user, "edit")
    try:
        return set_plugin_enabled(db, plugin_id, body.enabled)
    except PluginDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/plugins/{plugin_id}/permissions", response_model=list[PluginPermissionGrantOut])
def list_plugin_permissions(plugin_id: str, db: DbSession) -> list[PluginPermissionGrant]:
    try:
        return list_plugin_permission_grants(db, plugin_id)
    except PluginDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/plugins/{plugin_id}/permissions", response_model=list[PluginPermissionGrantOut])
def update_plugin_permissions(
    plugin_id: str,
    body: PluginPermissionGrantUpdate,
    db: DbSession,
    user: CurrentUser,
) -> list[PluginPermissionGrant]:
    # Granting a plugin its permissions is the escalation path: an ungated caller could grant
    # and then invoke in two requests.
    ensure_instance_admin(db, user, "edit")
    try:
        return set_plugin_permission_grants(db, plugin_id, body.grants)
    except PluginDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plugins/tools", response_model=list[PluginToolOut])
def list_plugin_tools(db: DbSession) -> list[dict]:
    return list_enabled_plugin_tools(db)


@router.post("/plugins/{plugin_id}/tools/{tool_name}/invoke", response_model=PluginInvocationOut)
def invoke_tool(
    plugin_id: str, tool_name: str, body: PluginInvokeRequest, db: DbSession, user: CurrentUser
) -> PluginInvocation:
    ensure_instance_admin(db, user, "edit")
    try:
        return invoke_plugin_tool(db, plugin_id, tool_name, body.input)
    except PluginDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plugins/invocations", response_model=list[PluginInvocationOut])
def list_invocations(db: DbSession, user: CurrentUser, plugin_id: str | None = None) -> list[PluginInvocation]:
    ensure_instance_admin(db, user, "edit")
    stmt = select(PluginInvocation)
    if plugin_id:
        stmt = stmt.where(PluginInvocation.plugin_id == plugin_id)
    stmt = stmt.order_by(PluginInvocation.created_at.desc())
    return list(db.scalars(stmt))


@router.delete("/plugins/invocations/{invocation_id}", status_code=204)
def delete_invocation(invocation_id: str, db: DbSession, user: CurrentUser) -> None:
    ensure_instance_admin(db, user, "edit")
    obj = db.get(PluginInvocation, invocation_id)
    if obj is not None:
        db.delete(obj)
        db.commit()


@router.delete("/plugins/invocations", status_code=204)
def clear_invocations(db: DbSession, user: CurrentUser, plugin_id: str | None = None) -> None:
    ensure_instance_admin(db, user, "edit")
    """清空调用记录;带 plugin_id 只清该插件的。"""
    stmt = select(PluginInvocation)
    if plugin_id:
        stmt = stmt.where(PluginInvocation.plugin_id == plugin_id)
    for obj in db.scalars(stmt):
        db.delete(obj)
    db.commit()
