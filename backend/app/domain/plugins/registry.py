from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Plugin, PluginInvocation, PluginPermissionGrant

MANIFEST_FILENAMES = ("mibu.plugin.json", "plugin.json")


class PluginDomainError(ValueError):
    pass


def scan_plugins(db: Session, plugins_dir: Path) -> list[Plugin]:
    plugins_dir.mkdir(parents=True, exist_ok=True)
    scanned: list[Plugin] = []
    for manifest_path in _iter_manifest_paths(plugins_dir):
        manifest = _load_manifest(manifest_path)
        plugin_id = _required_string(manifest, "id", manifest_path)
        name = _required_string(manifest, "name", manifest_path)
        version = _required_string(manifest, "version", manifest_path)
        plugin = db.get(Plugin, plugin_id)
        if plugin is None:
            plugin = Plugin(id=plugin_id, name=name, version=version, enabled=False, manifest=manifest)
            db.add(plugin)
        else:
            plugin.name = name
            plugin.version = version
            plugin.manifest = manifest
        _sync_permission_grants(db, plugin)
        scanned.append(plugin)
    db.commit()
    for plugin in scanned:
        db.refresh(plugin)
    return scanned


def set_plugin_enabled(db: Session, plugin_id: str, enabled: bool) -> Plugin:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise PluginDomainError("Plugin not found")
    plugin.enabled = enabled
    db.commit()
    db.refresh(plugin)
    return plugin


def list_enabled_plugin_tools(db: Session) -> list[dict[str, Any]]:
    plugins = db.scalars(select(Plugin).where(Plugin.enabled.is_(True)).order_by(Plugin.name)).all()
    tools: list[dict[str, Any]] = []
    for plugin in plugins:
        if not plugin_permissions_granted(db, plugin):
            continue
        for tool in _manifest_tools(plugin.manifest):
            tools.append(_tool_descriptor(plugin, tool))
    return tools


def list_plugin_permission_grants(db: Session, plugin_id: str) -> list[PluginPermissionGrant]:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise PluginDomainError("Plugin not found")
    _sync_permission_grants(db, plugin)
    db.commit()
    return list(
        db.scalars(
            select(PluginPermissionGrant)
            .where(PluginPermissionGrant.plugin_id == plugin_id)
            .order_by(PluginPermissionGrant.permission)
        )
    )


def set_plugin_permission_grants(db: Session, plugin_id: str, grants: dict[str, bool]) -> list[PluginPermissionGrant]:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise PluginDomainError("Plugin not found")
    allowed = set(_manifest_permissions(plugin.manifest))
    unknown = sorted(set(grants) - allowed)
    if unknown:
        raise PluginDomainError(f"Unknown plugin permissions: {', '.join(unknown)}")
    _sync_permission_grants(db, plugin)
    for permission, granted in grants.items():
        grant = db.get(PluginPermissionGrant, {"plugin_id": plugin_id, "permission": permission})
        if grant is not None:
            grant.granted = granted
    db.commit()
    return list_plugin_permission_grants(db, plugin_id)


def plugin_permissions_granted(db: Session, plugin: Plugin) -> bool:
    permissions = _manifest_permissions(plugin.manifest)
    if not permissions:
        return True
    grants = {
        grant.permission: grant.granted
        for grant in db.scalars(select(PluginPermissionGrant).where(PluginPermissionGrant.plugin_id == plugin.id))
    }
    return all(grants.get(permission) is True for permission in permissions)


def invoke_plugin_tool(db: Session, plugin_id: str, tool_name: str, input_payload: dict[str, Any]) -> PluginInvocation:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise PluginDomainError("Plugin not found")
    if not plugin.enabled:
        raise PluginDomainError("Plugin is disabled")
    if not plugin_permissions_granted(db, plugin):
        raise PluginDomainError("Plugin permissions are not granted")
    tool = _find_tool(plugin.manifest, tool_name)
    if tool is None:
        raise PluginDomainError("Plugin tool not found")

    invocation = PluginInvocation(
        plugin_id=plugin.id,
        tool_name=tool_name,
        status="queued",
        input=input_payload,
        output={
            "mode": "deferred",
            "message": "Invocation recorded. Runtime execution adapter is not attached yet.",
        },
    )
    db.add(invocation)
    db.commit()
    db.refresh(invocation)
    return invocation


def _iter_manifest_paths(plugins_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for child in sorted(plugins_dir.iterdir()):
        if not child.is_dir():
            continue
        for filename in MANIFEST_FILENAMES:
            manifest_path = child / filename
            if manifest_path.exists():
                paths.append(manifest_path)
                break
    return paths


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PluginDomainError(f"Invalid plugin manifest JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise PluginDomainError(f"Plugin manifest must be an object: {path}")
    raw["_path"] = str(path.parent)
    raw.setdefault("tools", [])
    raw.setdefault("skills", [])
    raw.setdefault("permissions", [])
    return raw


def _sync_permission_grants(db: Session, plugin: Plugin) -> None:
    for permission in _manifest_permissions(plugin.manifest):
        grant = db.get(PluginPermissionGrant, {"plugin_id": plugin.id, "permission": permission})
        if grant is None:
            db.add(PluginPermissionGrant(plugin_id=plugin.id, permission=permission, granted=False))


def _required_string(manifest: dict[str, Any], key: str, path: Path) -> str:
    value = manifest.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginDomainError(f"Plugin manifest {path} requires string field: {key}")
    return value.strip()


def _manifest_tools(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    tools = manifest.get("tools", [])
    if not isinstance(tools, list):
        return []
    return [tool for tool in tools if isinstance(tool, dict) and isinstance(tool.get("name"), str)]


def _manifest_permissions(manifest: dict[str, Any]) -> list[str]:
    permissions = manifest.get("permissions", [])
    if not isinstance(permissions, list):
        return []
    return [permission for permission in permissions if isinstance(permission, str) and permission.strip()]


def _find_tool(manifest: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    for tool in _manifest_tools(manifest):
        if tool.get("name") == tool_name:
            return tool
    return None


def _tool_descriptor(plugin: Plugin, tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "plugin_id": plugin.id,
        "plugin_name": plugin.name,
        "tool_name": tool["name"],
        "description": tool.get("description", ""),
        "input_schema": tool.get("input_schema", {"type": "object"}),
        "permissions": plugin.manifest.get("permissions", []),
        "skills": plugin.manifest.get("skills", []),
    }
