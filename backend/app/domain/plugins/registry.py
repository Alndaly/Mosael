from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Plugin, PluginInvocation, PluginPermissionGrant
from app.domain.plugins.credentials import env_for as credential_env, missing as missing_credentials
from app.domain.plugins.mcp_bridge import McpBridgeError, call_tool as mcp_call_tool, discover_tools, is_mcp
from app.domain.plugins.runtime import PluginRuntimeError, check_required_input, execute_tool

#: 按顺序探测。`open-studio.plugin.json` 是现在的规范名,`plugin.json` 是通用名,
#: `mibu.plugin.json` 是更名前的写法——用户磁盘上的既有插件还带着它,去掉会让那些插件直接消失。
MANIFEST_FILENAMES = ("open-studio.plugin.json", "plugin.json", "mibu.plugin.json")

#: MCP 插件的工具清单是从 server 现拉的,缓存在 manifest 的这个键下。下划线开头 = 运行时注入,
#: 和 `_path` 同一类;重扫 manifest 文件时会被特意搬过来,不然每次扫描都要重连一遍 server。
DISCOVERED_TOOLS_KEY = "_discovered_tools"


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
            # MCP 插件的工具清单不在 manifest 文件里,重扫时从旧记录搬过来 —— 否则一次扫描就把
            # 已发现的工具清空,插件在工作流下拉和智能体工具表里凭空消失,直到用户想起来去刷新。
            cached = plugin.manifest.get(DISCOVERED_TOOLS_KEY) if isinstance(plugin.manifest, dict) else None
            if cached and DISCOVERED_TOOLS_KEY not in manifest:
                manifest[DISCOVERED_TOOLS_KEY] = cached
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
    # MCP 插件启用时顺手拉一次工具清单:没有它,插件启用了但工具表是空的,而"为什么没工具"
    # 这个问题在界面上无处可答。失败不阻止启用 —— 常见原因是凭据还没填,而填凭据的入口正是
    # 启用之后那张卡片;卡在这里会变成死结。错误留给 refresh_plugin_tools 显式报。
    if enabled and is_mcp(plugin.manifest):
        try:
            refresh_plugin_tools(db, plugin_id)
        except PluginDomainError:
            pass
    db.refresh(plugin)
    return plugin


def refresh_plugin_tools(db: Session, plugin_id: str) -> Plugin:
    """向 MCP 插件的 server 重新要一次工具清单。进程类插件的清单写在 manifest 里,无需刷新。"""
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise PluginDomainError("Plugin not found")
    if not is_mcp(plugin.manifest):
        return plugin
    absent = missing_credentials(db, plugin)
    if absent:
        raise PluginDomainError(f"请先填写插件凭据: {', '.join(absent)}")
    try:
        tools = discover_tools(plugin.manifest, credential_env(db, plugin))
    except McpBridgeError as exc:
        raise PluginDomainError(str(exc)) from exc
    # manifest 是 JSON 列,原地改字典 SQLAlchemy 看不见,必须整份换掉。
    plugin.manifest = {**plugin.manifest, DISCOVERED_TOOLS_KEY: tools}
    db.commit()
    db.refresh(plugin)
    return plugin


def list_enabled_plugin_tools(db: Session) -> list[dict[str, Any]]:
    plugins = db.scalars(select(Plugin).where(Plugin.enabled.is_(True)).order_by(Plugin.name)).all()
    tools: list[dict[str, Any]] = []
    for plugin in plugins:
        if not plugin_permissions_granted(db, plugin):
            continue
        if missing_credentials(db, plugin):
            # 缺凭据的插件不进工具表:让智能体调一个必定 401 的工具,只会烧掉一轮对话来
            # 复述一句用户在设置页早就能看到的话。
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
        status="running",
        input=input_payload,
        output={},
    )
    db.add(invocation)
    db.commit()

    # Process-isolated execution (plan §19.6): a broken plugin fails its own
    # invocation record, never the app.
    try:
        check_required_input(tool, input_payload)
        absent = missing_credentials(db, plugin)
        if absent:
            raise PluginRuntimeError(f"插件凭据未填写: {', '.join(absent)}")
        env = credential_env(db, plugin)
        if is_mcp(plugin.manifest):
            output = mcp_call_tool(plugin.manifest, tool_name, input_payload, env)
        else:
            output = execute_tool(plugin.manifest, tool_name, input_payload, env)
        invocation.status = "succeeded"
        invocation.output = output
    except (PluginRuntimeError, McpBridgeError) as exc:
        invocation.status = "failed"
        invocation.error = str(exc)
    except Exception as exc:  # noqa: BLE001 — defensive: runtime must never bubble
        invocation.status = "failed"
        invocation.error = f"插件运行时异常: {exc}"
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
    if not is_mcp(manifest):
        return _tool_entries(manifest.get("tools"))
    # MCP 插件的清单来自 server 本身。manifest 文件里的 tools 不是第二份清单,而是**按名字的
    # 覆盖层** —— 目前唯一有意义的覆盖是 read_only:server 报的工具默认不算只读(子智能体因此
    # 拿不到),要放开得由装这个插件的人明说,那是一个人类判断,不该由被接入的一方自己声称。
    # 只认 read_only 这一个键:让 manifest 顺手覆盖 description / input_schema,等于又造出一份
    # 会随 server 升级而烂掉的手抄清单,而这正是"清单从 server 现拉"要避免的东西。
    read_only = {
        tool["name"] for tool in _tool_entries(manifest.get("tools")) if tool.get("read_only") is True
    }
    return [
        {**tool, "read_only": tool["name"] in read_only}
        for tool in _tool_entries(manifest.get(DISCOVERED_TOOLS_KEY))
    ]


def _tool_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [tool for tool in raw if isinstance(tool, dict) and isinstance(tool.get("name"), str)]


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
        "kind": "mcp" if is_mcp(plugin.manifest) else "process",
        "tool_name": tool["name"],
        "description": tool.get("description", ""),
        # 只读声明。默认 False:插件跑的是别人的代码,"不确定"必须落在保守那边。
        "read_only": tool.get("read_only") is True,
        "input_schema": tool.get("input_schema", {"type": "object"}),
        "permissions": plugin.manifest.get("permissions", []),
        "skills": plugin.manifest.get("skills", []),
    }
