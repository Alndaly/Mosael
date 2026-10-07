"""存着的工作流的工具,不在这一轮工具表里时怎么够得着(ADR 0044 修订 2026-10-08)。

工作台那一轮只发用得上的那几张工作流的工具(画布上开着的、这段对话调过的、用户点过名的,见 tool_manifest)。别的那几张
经这里:查它的工具收哪些入参、某个下拉有哪些值(`comfy_workflow_inputs`),按它跑一次(`comfy_run_workflow` 开的卡,见
confirmable/comfyui —— 批准之后走的是那个工具自己的那一套:同一个校验、同一个执行入口、同一份卡上的说明)。

「哪张工作流」认三种写法:`list_workflows` 回的 `tool`、智能体看到的完整工具名、工作流的路径(带不带 `.json` 都认)。只在这个人
自己接的连接里找(连接归人);只看插件报的 `workflow` 键,不看工具名长什么样。

**只认进得了智能体工具表的那几个**(ADR 0045 §5):有表单的工作流,它的完整工作流工具插件标了 `agent: false` —— 给智能体的是
表单那一项。一张工作流的几个入口 `workflow.path` 相同,按路径找到的就是表单入口;这条路不把 `agent: false` 的绕回来(要全部
参数,智能体走生成那一路、带完整工作流的模型 id)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import User
from app.domain.agent.plugin_schema import compact_property
from app.domain.agent.tool_manifest import agent_tool_name

#: 一个下拉的可选值一次最多回多少个(按 `query` 筛过之后)。
MAX_OPTIONS = 100
#: 入参名对不上时,报错里列出的接受的入参名最多几个。
_MAX_ACCEPTED_LISTED = 60


class WorkflowToolError(LocalizedError, ValueError):
    """指不到那张工作流 / 那一格入参,或者给了它不认的入参名。带文案 key(`workbenchErr_*`)。"""


def _bare(path: str) -> str:
    return path[: -len(".json")] if path.lower().endswith(".json") else path


def resolve(db: Session, user: User, workflow: str, instance_id: str = "") -> tuple[dict[str, Any], str]:
    """`workflow` 指的那张工作流的工具,和它在智能体工具表里的名字。两台连接上都有同一个路径时要给 `instance_id`。"""
    from app.domain.plugins.tools import exposed

    wanted = workflow.strip()
    if not wanted:
        raise WorkflowToolError("workbenchErr_noWorkflowTool", workflow=wanted)
    found: list[tuple[dict[str, Any], str]] = []
    for tool in exposed(db, user.id):
        if not tool.get("workflow") or not tool["agent"] or (instance_id and tool["instance_id"] != instance_id):
            continue
        name = agent_tool_name(tool["instance_id"], tool["name"])
        path = str(tool["workflow"].get("path") or "")
        if wanted in (tool["name"], name, path) or _bare(wanted) == _bare(path):
            found.append((tool, name))
    if not found:
        raise WorkflowToolError("workbenchErr_noWorkflowTool", workflow=wanted)
    if len({tool["instance_id"] for tool, _ in found}) > 1:
        names = "; ".join(f"{tool['instance_name']} = {tool['instance_id']}" for tool, _ in found[:10])
        raise WorkflowToolError("workbenchErr_whichConnection", names=names)
    return found[0]


def _properties(tool: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    return properties, [key for key in schema.get("required") or [] if key in properties]


def inputs(db: Session, user: User, workflow: str, input: str = "", query: str = "",  # noqa: A002 — 工具的入参名
           instance_id: str = "") -> dict[str, Any]:
    """`comfy_workflow_inputs`:一张工作流的工具收哪些入参(收紧过的写法,不设上限;`query` 按入参名、标题筛),或者 `input`
    那一格的可选值(`query` 按字筛,最多 `MAX_OPTIONS` 个,带总数)。"""
    tool, name = resolve(db, user, workflow, instance_id)
    properties, required = _properties(tool)
    needle = query.strip().lower()
    if input:
        spec = properties.get(input)
        if not isinstance(spec, dict):
            raise WorkflowToolError("workbenchErr_noWorkflowInput", input=input, tool=name)
        options = list(spec.get("enum") or [])
        matched = [one for one in options if needle in str(one).lower()] if needle else options
        return {"tool": name, "input": input, "title": spec.get("title") or input,
                **({"default": spec["default"]} if "default" in spec else {}),
                "total": len(options), "matched": len(matched), "options": matched[:MAX_OPTIONS]}
    listed = {key: compact_property(spec) for key, spec in properties.items()
              if not needle or needle in key.lower() or needle in str((spec or {}).get("title") or "").lower()}
    return {"tool": name, "workflow": tool["workflow"].get("path"), "label": tool["label"], "inputs": listed,
            "required": required}


def checked_call(db: Session, user: User, workflow: str, arguments: dict[str, Any], instance_id: str = "") -> str:
    """`comfy_run_workflow` 开卡时:认出是哪张工作流的工具、入参名都是它认得的(认不得的不悄悄丢掉 —— 丢了它就带着缺省值
    跑了另一件事)。回那个工具在智能体工具表里的名字。"""
    tool, name = resolve(db, user, workflow, instance_id)
    properties, _ = _properties(tool)
    unknown = sorted(key for key in arguments if key not in properties)
    if unknown:
        accepted = list(properties)
        listed = ", ".join(accepted[:_MAX_ACCEPTED_LISTED]) + (" …" if len(accepted) > _MAX_ACCEPTED_LISTED else "")
        raise WorkflowToolError("workbenchErr_unknownWorkflowInputs", keys=", ".join(unknown), tool=name, accepted=listed)
    return name


__all__ = ["MAX_OPTIONS", "WorkflowToolError", "checked_call", "inputs", "resolve"]
