from __future__ import annotations

import json
import logging
import shutil
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

logger = logging.getLogger(__name__)

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
    _prune_uninstalled(db, plugins_dir)
    db.commit()
    for plugin in scanned:
        db.refresh(plugin)
    return scanned


def _prune_uninstalled(db: Session, plugins_dir: Path) -> None:
    """把目录已经不在了的插件记录一并删掉。

    从磁盘上删掉一个插件目录之后,它的记录以前会一直挂在列表里 —— 点进去是个空壳,而"为什么
    它还在"这件事在界面上无处可答。

    **判据是每个插件自己的目录**,不是"这次扫到了谁"。两者在正常情况下等价,但在异常情况下
    差别很大:插件目录整体读不到时(权限、外挂盘没挂上),按"没扫到"会把**全部**记录连同
    已授的权限和已填的凭据一起抹掉;按各自的目录则只删真的不见了的那些。

    再加一道闸:plugins_dir 本身不存在就整个不修剪。scan 开头会 mkdir,所以这条平时不触发 ——
    它防的是有人不经 scan 直接调进来的情况。
    """
    if not plugins_dir.is_dir():
        return
    root = plugins_dir.resolve()
    for plugin in db.scalars(select(Plugin)):
        raw = (plugin.manifest or {}).get("_path") if isinstance(plugin.manifest, dict) else None
        if not raw:
            continue
        path = Path(str(raw))
        # 只处理登记在这个插件目录下的记录;别人塞进来的路径不由这里判生死。
        if root not in path.resolve().parents:
            continue
        if not any((path / name).exists() for name in MANIFEST_FILENAMES):
            logger.info("plugin %s removed: %s no longer holds a manifest", plugin.id, path)
            db.delete(plugin)


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


def uninstall_plugin(db: Session, plugin_id: str, plugins_dir: Path) -> None:
    """卸载:删掉插件目录,再删掉记录。

    权限、凭据、调用记录随外键级联一起走(建表时声明了 ondelete="CASCADE",连接层开着
    PRAGMA foreign_keys=ON)。凭据尤其不能留:插件都不在了还躺着一份没有主人、界面上也没有
    任何入口能看到的密钥。

    **必须连目录一起删**。只清记录的话,下一次扫描又把它装回来 —— 用户看到的是"我删了它
    怎么又回来了",而这个页面上没有任何东西能解释那件事。

    删之前认两件事:目录是 plugins_dir 的**直接子目录**,而且里面确实有一份清单文件。
    manifest 的 `_path` 是扫描时写进去的,正常情况下必然满足;但这是一次 rmtree,
    "正常情况下"不足以作为动手的理由。
    """
    plugin = db.get(Plugin, plugin_id)
    if plugin is None:
        raise PluginDomainError("Plugin not found")
    raw = (plugin.manifest or {}).get("_path") if isinstance(plugin.manifest, dict) else None
    if raw:
        path = Path(str(raw)).resolve()
        root = plugins_dir.resolve()
        has_manifest = any((path / name).exists() for name in MANIFEST_FILENAMES)
        if path.parent == root and path.is_dir() and has_manifest:
            shutil.rmtree(path)
        elif path.is_dir():
            # 目录还在但不符合上面的形状:不动它,只清记录。宁可留下一个孤儿目录,
            # 也不要在一条来路不明的路径上跑 rmtree。
            logger.warning("plugin %s: refusing to remove %s (not a direct child of %s)", plugin_id, path, root)
    db.delete(plugin)
    db.commit()


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
