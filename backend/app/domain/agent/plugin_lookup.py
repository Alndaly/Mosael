"""这一轮工具表里没有的插件工具,怎么够得着(ADR 0044 修订 2026-10-08)。

每一轮只发**用得上的**插件工具的完整定义(见 tool_manifest):ComfyUI 工作台里是画布上开着的那张工作流、这段对话调过的、用户
点过名的;工作台以外的通用插件工具(Blender、Manim……)是这段对话调过的。别的经这里:

- `plugin_tools`:不带 `tool` 按字找这一处够得着的插件工具;带 `tool` 看它的完整说明和全部入参(收紧过的写法,不设上限);
  再带 `input` 看那一格的可选值;
- `run_plugin_tool`:调一次 —— 开的卡见 confirmable/plugin_tools,卡上的说明、问人的那一档、开卡校验和批准后的执行都是那个工具
  自己的那一份。

只在这个人自己接的连接里找(连接归人),只找**这一处这一轮发的那几份**里的(`tool_manifest.session_kits`:工作台里是 ComfyUI 的,
别处是通用插件的)。「哪个工具」认三种写法:智能体看到的完整名字、插件里的工具名、工作流的路径(带不带 `.json` 都认)。后两种在两台
连接上撞了就报错、列出各自的完整名字 —— 完整名字带着连接,不另设一个「哪台连接」的参数。

**只认进得了智能体工具表的那几个**(ADR 0045 §5):有表单的工作流,它的完整工作流工具插件标了 `agent: false` —— 给智能体的是
表单那一项。一张工作流的几个入口 `workflow.path` 相同,按路径找到的就是表单入口。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import User
from app.domain.agent.plugin_schema import compact_property
from app.domain.agent.tool_manifest import agent_plugin_tools, agent_tool_name, session_kits

#: 按字找一次最多回多少个。
MAX_FOUND = 40
#: 一个下拉的可选值一次最多回多少个(按 `query` 筛过之后)。
MAX_OPTIONS = 100
#: 入参名对不上时,报错里列出的接受的入参名最多几个。
_MAX_ACCEPTED_LISTED = 60
#: 找到的每一个带多少字的说明(第一行)。
_ABOUT_CHARS = 160


class PluginLookupError(LocalizedError, ValueError):
    """指不到那个工具 / 那一格入参,或者给了它不认的入参名。带文案 key(`pluginToolErr_*`)。"""


def _bare(path: str) -> str:
    return path[: -len(".json")] if path.lower().endswith(".json") else path


def _path(tool: dict[str, Any]) -> str:
    return str((tool.get("workflow") or {}).get("path") or "")


def _reachable(db: Session, user: User, session_id: str) -> list[tuple[dict[str, Any], str]]:
    """这个人在这一处够得着的插件工具(进得了智能体工具表的,见 tool_manifest.agent_plugin_tools),和它们在工具表里的名字。"""
    return [(tool, agent_tool_name(tool["instance_id"], tool["name"]))
            for tool, _kit in agent_plugin_tools(db, user.id, session_kits(db, session_id))]


def resolve(db: Session, user: User, tool: str, session_id: str = "") -> tuple[dict[str, Any], str]:
    """`tool` 指的那个插件工具,和它在智能体工具表里的名字。"""
    wanted = tool.strip()
    if not wanted:
        raise PluginLookupError("pluginToolErr_notFound", tool=wanted)
    found = []
    for one, name in _reachable(db, user, session_id):
        path = _path(one)
        if wanted in (one["name"], name) or (path and _bare(wanted) == _bare(path)):
            found.append((one, name))
    if not found:
        raise PluginLookupError("pluginToolErr_notFound", tool=wanted)
    if len({one["instance_id"] for one, _ in found}) > 1:
        names = "; ".join(f"{one['instance_name']}: {name}" for one, name in found[:10])
        raise PluginLookupError("pluginToolErr_whichConnection", names=names)
    return found[0]


def _properties(tool: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    return properties, [key for key in schema.get("required") or [] if key in properties]


def _asks(tool: dict[str, Any]) -> bool:
    from app.domain.effects import needs_card

    return needs_card(tool["effects"])


def _found(tool: dict[str, Any], name: str) -> dict[str, Any]:
    about = str(tool.get("description") or "").strip().splitlines()
    path = _path(tool)
    return {"tool": name, "label": tool["label"], "connection": tool["instance_name"],
            "about": about[0][:_ABOUT_CHARS] if about else "", "asks": _asks(tool), **({"workflow": path} if path else {})}


def lookup(db: Session, user: User, query: str = "", tool: str = "", input: str = "",  # noqa: A002 — 工具的入参名
           session_id: str = "") -> dict[str, Any]:
    """`plugin_tools`(见模块说明)。`query`:不带 `tool` 时找工具的字(都要出现在名字、标题、说明、连接名、路径里);带 `tool`
    时筛入参(按名字、标题);带 `input` 时筛可选值。"""
    needle = query.strip().lower()
    if not tool:
        reachable = _reachable(db, user, session_id)
        words = needle.split()
        matched = [_found(one, name) for one, name in reachable
                   if all(word in " ".join((name, str(one["label"]), str(one.get("description") or ""),
                                            one["instance_name"], _path(one))).lower() for word in words)]
        return {"total": len(reachable), "matched": len(matched), "tools": matched[:MAX_FOUND]}
    one, name = resolve(db, user, tool, session_id)
    properties, required = _properties(one)
    if input:
        spec = properties.get(input)
        if not isinstance(spec, dict):
            raise PluginLookupError("pluginToolErr_noInput", input=input, tool=name)
        options = list(spec.get("enum") or [])
        matched = [option for option in options if needle in str(option).lower()] if needle else options
        return {"tool": name, "input": input, "title": spec.get("title") or input,
                **({"default": spec["default"]} if "default" in spec else {}),
                "total": len(options), "matched": len(matched), "options": matched[:MAX_OPTIONS]}
    listed = {key: compact_property(spec) for key, spec in properties.items()
              if not needle or needle in key.lower() or needle in str((spec or {}).get("title") or "").lower()}
    return {**_found(one, name), "description": one.get("description") or "", "inputs": listed, "required": required}


def resolve_name(db: Session, user: User, tool: str, session_id: str = "") -> str:
    """`run_plugin_tool` 开卡之前:认出是哪个工具(只在这一处够得着的里认),回它在智能体工具表里的名字 —— 卡记的是它。"""
    return resolve(db, user, tool, session_id)[1]


def unknown_inputs(tool: dict[str, Any], arguments: dict[str, Any]) -> None:
    """入参名都得是它认得的:认不得的不悄悄丢掉 —— 丢了它就带着缺省值跑了另一件事。"""
    schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
    if schema.get("additionalProperties") not in (None, False):
        return
    properties, _ = _properties(tool)
    unknown = sorted(key for key in arguments if key not in properties)
    if unknown:
        accepted = list(properties)
        listed = ", ".join(accepted[:_MAX_ACCEPTED_LISTED]) + (" …" if len(accepted) > _MAX_ACCEPTED_LISTED else "")
        raise PluginLookupError("pluginToolErr_unknownInputs", keys=", ".join(unknown), tool=tool["label"], accepted=listed)


__all__ = ["MAX_FOUND", "MAX_OPTIONS", "PluginLookupError", "lookup", "resolve", "resolve_name", "unknown_inputs"]
