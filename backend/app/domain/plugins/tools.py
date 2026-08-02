"""实例的**能力**:有哪些工具、哪些对外暴露、怎么调一次。

这是插件唯一的执行路径。智能体、工作流、插件页手动试跑三条入口都走 `invoke` ——
权限校验、凭据注入、调用留痕都在这里,没有谁能绕过它。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PluginInstance, PluginInvocation, PluginPackage
from app.domain.plugins import instances as inst
from app.domain.plugins.manifest import Manifest
from app.domain.plugins.mcp_bridge import McpBridgeError, call_tool as mcp_call, discover_tools
from app.domain.plugins.packages import PluginDomainError, manifest_of
from app.domain.plugins.runtime import PluginRuntimeError, check_required_input, execute_tool


def all_tools(db: Session, instance: PluginInstance) -> list[dict[str, Any]]:
    """这个实例**拥有**的工具(不管暴不暴露)。插件页的勾选列表用它。

    进程类插件的清单写在 manifest 里;MCP 实例的清单从服务现拉、缓存在 instance 上 ——
    手抄一份端点清单会随服务升级而烂,而且烂得很安静。
    """
    manifest = inst.manifest_for(db, instance)
    raw = instance.discovered_tools if manifest.is_mcp else manifest.declared_tools
    out: list[dict[str, Any]] = []
    for tool in raw or []:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            continue
        override = manifest.overrides.get(tool["name"])
        out.append(
            {
                "name": tool["name"],
                "label": (override.label if override and override.label else "") or tool["name"],
                "description": (override.description if override and override.description else "")
                or str(tool.get("description") or ""),
                "input_schema": tool.get("input_schema") or {"type": "object", "properties": {}},
                # 只读默认 False:插件跑的是别人的代码,没有确认门也照样能发请求、写文件,
                # 所以"不确定"落在保守那边 —— 子智能体只拿只读工具。
                #
                # 两个来源:工具自己声明的(进程插件写在 declare 里),和 overrides 里覆盖的
                # (MCP 插件只能这么写 —— 它的清单是从服务拉的)。任一处标了就算。
                "read_only": bool((override and override.read_only) or tool.get("read_only")),
                "node": (override.node if override else None) or tool.get("node"),
            }
        )
    return out


def refresh_tools(db: Session, instance: PluginInstance) -> PluginInstance:
    """向 MCP 服务重新要一次工具清单。进程类实例的清单写在 manifest 里,无需刷新。"""
    manifest = inst.manifest_for(db, instance)
    if not manifest.is_mcp:
        inst.seed_capabilities(db, instance, manifest, [t["name"] for t in all_tools(db, instance)])
        return instance
    for absent in (inst.missing_config(db, instance), inst.missing_credentials(db, instance)):
        if absent:
            raise PluginDomainError(f"请先填写: {'、'.join(absent)}")
    try:
        discovered = discover_tools(_runtime_manifest(manifest), inst.secrets_for(db, instance))
    except McpBridgeError as exc:
        raise PluginDomainError(str(exc)) from exc
    instance.discovered_tools = discovered
    db.commit()
    db.refresh(instance)
    inst.seed_capabilities(db, instance, manifest, [t["name"] for t in discovered])
    return instance


def _runtime_manifest(manifest: Manifest) -> dict[str, Any]:
    """mcp_bridge 收的是一个字典(它比这次重构更早)。在这里做一次转换,而不是把 dataclass
    的形状泄进传输层 —— 那一层只关心怎么连、连哪儿。"""
    runtime = manifest.runtime
    return {
        "_path": manifest.path,
        "kind": "mcp",
        "mcp": {
            "transport": runtime.transport,
            "command": runtime.command,
            "args": runtime.args,
            "url": runtime.url,
            "headers": runtime.headers,
        },
    }


def exposed(db: Session) -> list[dict[str, Any]]:
    """所有**可用**实例暴露出来的工具。智能体工具表、工作流节点面板、插件页共用这一份。

    可用 = 启用 + 配置齐 + 凭据齐 + 权限已授。不可用的实例整条不出现 —— 让智能体去调一个
    必定 401 的工具,只会烧掉一轮对话来复述一句用户在设置页早就看得到的话。
    """
    out: list[dict[str, Any]] = []
    for instance in db.scalars(select(PluginInstance).where(PluginInstance.enabled.is_(True))):
        if inst.blocked_reason(db, instance):
            continue
        package = db.get(PluginPackage, instance.package_id)
        if package is None:
            continue
        chosen = inst.exposed_tools(db, instance.id)
        for tool in all_tools(db, instance):
            if tool["name"] not in chosen:
                continue
            out.append({**tool, "instance_id": instance.id, "instance_name": instance.name, "package_id": package.id})
    return out


def find(db: Session, instance_id: str, tool_name: str) -> dict[str, Any] | None:
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        return None
    return next((tool for tool in all_tools(db, instance) if tool["name"] == tool_name), None)


def invoke(db: Session, instance_id: str, tool_name: str, payload: dict[str, Any]) -> PluginInvocation:
    """跑一次工具。**插件唯一的执行路径。**"""
    instance = db.get(PluginInstance, instance_id)
    if instance is None:
        raise PluginDomainError("Plugin instance not found")
    blocked = inst.blocked_reason(db, instance)
    if blocked:
        raise PluginDomainError(f"「{instance.name}」不可用:{blocked}")
    tool = find(db, instance_id, tool_name)
    if tool is None:
        raise PluginDomainError(f"「{instance.name}」没有工具 {tool_name}")

    invocation = PluginInvocation(
        instance_id=instance.id, tool_name=tool_name, status="running", input=payload, output={}
    )
    db.add(invocation)
    db.commit()

    manifest = inst.manifest_for(db, instance)
    # 进程隔离:插件崩了、超时了、吐了非 JSON —— 失败的是这次调用记录,不是应用。
    try:
        check_required_input(tool, payload)
        if manifest.is_mcp:
            output = mcp_call(_runtime_manifest(manifest), tool_name, payload, inst.secrets_for(db, instance))
        else:
            output = execute_tool(
                {"_path": manifest.path, "entry": manifest.runtime.entry},
                tool_name,
                payload,
                inst.process_env(db, instance),
            )
        invocation.status, invocation.output = "succeeded", output
    except (PluginRuntimeError, McpBridgeError) as exc:
        invocation.status, invocation.error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 — runtime must never bubble
        invocation.status, invocation.error = "failed", f"插件运行时异常: {exc}"
    db.commit()
    db.refresh(invocation)
    return invocation


__all__ = ["all_tools", "exposed", "find", "invoke", "refresh_tools"]
