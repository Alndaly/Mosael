"""实例的**能力**:有哪些工具、哪些对外暴露、怎么调一次。

这是插件唯一的执行路径。智能体、工作流、插件页手动试跑三条入口都走 `invoke` ——
权限校验、凭据注入、调用留痕都在这里,没有谁能绕过它。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import get_current_locale
from app.db.models import PluginInstance, PluginInvocation, PluginPackage
from app.domain.plugins import artifacts, inputs as plugin_inputs, instances as inst, state as plugin_state
from app.domain.plugins.artifacts import ArtifactError, cleanup_scratch_dir, make_scratch_dir
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import Manifest, text_of
from app.domain.plugins.mcp_bridge import McpBridgeError, call_tool as mcp_call, discover_tools
from app.domain.plugins.runtime import PluginRuntimeError, check_required_input, execute_tool


def _short_description_label(description: str) -> str:
    """从缺少 ``title`` 的旧 MCP 工具描述里取一个可读名称。

    MCP 的 ``Tool.title`` 是可选字段，TikHub 等不少服务只把短名称写在 description，形如
    ``获取视频详情/Get video detail``。把整段描述永远当标题会制造另一种坏 UI，所以这里只
    接受第一行里足够短的一半；不满足就继续回退到人性化后的稳定名。
    """
    first_line = next((line.strip() for line in description.splitlines() if line.strip()), "")
    if not first_line:
        return ""
    parts = [part.strip() for part in first_line.split("/", 1)]
    locale = get_current_locale()
    candidate = parts[1] if locale == "en" and len(parts) > 1 else parts[0]
    candidate = candidate.strip().rstrip("。.!！?？;；")
    return candidate if 1 <= len(candidate) <= 48 else ""


def _humanize_tool_name(name: str) -> str:
    """最后一道展示兜底；稳定的调用名仍原样保存在 ``name``。"""
    words = " ".join(name.replace("-", "_").split("_")).strip()
    return words[:1].upper() + words[1:] if words else name


def _display_label(tool: dict[str, Any], override_label: str = "") -> str:
    """插件工具唯一的展示名称解析入口。"""
    description = text_of(tool.get("description"))
    return (
        override_label.strip()
        or text_of(tool.get("title"))
        or text_of(tool.get("label"))
        or _short_description_label(description)
        or _humanize_tool_name(str(tool.get("name") or ""))
    )


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
        description = (override.description if override and override.description else "") or text_of(
            tool.get("description")
        )
        out.append(
            {
                "name": tool["name"],
                "label": _display_label(tool, override.label if override else ""),
                "description": description,
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


def exposed(db: Session, user_id: str | None) -> list[dict[str, Any]]:
    """**他自己接的**那些可用实例暴露出来的工具。智能体工具表、工作流节点面板、插件页共用这一份。

    可用 = 启用 + 配置齐 + 凭据齐 + 权限已授。不可用的实例整条不出现 —— 让智能体去调一个
    必定 401 的工具,只会烧掉一轮对话来复述一句用户在设置页早就看得到的话。

    `user_id` 是**必填位置参数**(可以显式传 None 表示"不按人过滤",只有后台无人路径这么用):
    接入归人(见 db.models.PluginInstance),漏过滤的地方会让我的智能体拿着**别人的**第三方
    密钥去调 —— 那笔账记在他头上,我这边什么痕迹都没有。给个默认值就等于让漏改的地方静默通过。
    """
    out: list[dict[str, Any]] = []
    stmt = select(PluginInstance).where(PluginInstance.enabled.is_(True))
    if user_id is not None:
        stmt = stmt.where(PluginInstance.owner_user_id == user_id)
    for instance in db.scalars(stmt):
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


def invoke(
    db: Session,
    instance_id: str,
    tool_name: str,
    payload: dict[str, Any],
    *,
    workspace_id: str | None = None,
    project_id: str | None = None,
) -> PluginInvocation:
    """跑一次工具。**插件唯一的执行路径。**

    给了 workspace_id 的话,插件交出的文件产出会在这里收进素材库(见 artifacts):
    输出里的 `artifact` 换成 `asset_id`,调用方拿到的就是一个素材 id,和其它产素材的
    工具一样。没给 workspace_id 就不收 —— 一份素材总得属于某个工作区。
    """
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
    scratch: Path | None = None
    # 进程隔离:插件崩了、超时了、吐了非 JSON —— 失败的是这次调用记录,不是应用。
    try:
        check_required_input(tool, payload)
        if manifest.is_mcp:
            # MCP 那一侧没有 state 槽 —— 它是别人的协议,我们不往里加字段。要记东西的插件
            # 走进程形态(见 domain/plugins/state 的说明)。
            output = mcp_call(_runtime_manifest(manifest), tool_name, payload, inst.secrets_for(db, instance))
        else:
            scratch = make_scratch_dir()
            # 声明为素材的输入换成插件看得见的本地路径(见 plugins/inputs)。
            # 在这里而不是让插件自己取:它的环境里没有数据库、没有令牌、没有媒体目录,
            # 那是隔离边界的一部分。
            resolved = plugin_inputs.materialize(db, tool, payload, scratch, workspace_id=workspace_id)
            result = execute_tool(
                Path(manifest.path),
                manifest.runtime.entry,
                tool_name,
                resolved,
                inst.process_env(db, instance),
                scratch_dir=scratch,
            )
            output = result.output
            # 先落状态再收产出:刷新出来的令牌得先存住。反过来的话,收产出那一步出任何岔子
            # (下载失败、磁盘满),这次刷新就白做了 —— 而旧令牌已经被百度那边作废了。
            plugin_state.persist(db, instance, result.state)
        output = _collect_artifact(
            db, output, scratch, workspace_id=workspace_id, project_id=project_id, fallback_name=tool_name
        )
        invocation.status, invocation.output = "succeeded", output
    except (PluginRuntimeError, McpBridgeError, ArtifactError, PluginDomainError) as exc:
        invocation.status, invocation.error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001 — runtime must never bubble
        invocation.status, invocation.error = "failed", f"插件运行时异常: {exc}"
    finally:
        cleanup_scratch_dir(scratch)
    db.commit()
    db.refresh(invocation)
    return invocation


__all__ = ["all_tools", "exposed", "find", "invoke", "refresh_tools"]


def _collect_artifact(
    db: Session,
    output: dict[str, Any],
    scratch: Path | None,
    *,
    workspace_id: str | None,
    project_id: str | None,
    fallback_name: str,
) -> dict[str, Any]:
    """把输出里的文件产出收进素材库,`artifact` 换成 `asset_id`。

    换掉而不是两个都留:留着的话,下游会拿到一个指向已经删掉的暂存目录的路径 —— 那条路径
    在返回的那一刻就已经失效了(finally 里刚清完),而它看起来完全像个能用的路径。
    """
    spec = output.get("artifact")
    if not isinstance(spec, dict):
        return output
    if workspace_id is None or scratch is None:
        raise ArtifactError("这个工具产出了文件,但这次调用没有归属工作区,收不下")
    ref, name = artifacts.register(
        db, spec, scratch, workspace_id=workspace_id, project_id=project_id, fallback_name=fallback_name
    )
    return {**{k: v for k, v in output.items() if k != "artifact"}, "asset_id": ref, "asset_name": name}
