"""确认卡工具的登记表。加一个工具 = 加一条 `ConfirmableTool`。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

#: 权限档次(plan §17.4)。"edit" 最坏也撤得回;"render-cost"/"ai-cost" 花的是时间或钱;
#: "external" 的后果在这个应用之外 —— 发出去的帖子、别人服务器上的改动、本机跑过的代码。
PERMISSIONS = ("edit", "render-cost", "ai-cost", "external")
COSTS = ("none", "render", "ai")


@dataclass(frozen=True)
class ConfirmableTool:
    """一个会改东西的工具:开卡前怎么校验、卡上怎么说、批准之后做什么。

    - `validate(db, workspace_id, payload)` —— 说不通的请求**在开卡之前**就拒(一张注定执行不了
      的卡没有让用户去点的道理)。可以顺手把摘要要用的事实写回 payload。
    - `summarize(db, payload)` —— 卡上那句话。说的必须是待会儿真要做的事。
    - `execute(db, confirmation, actor)` —— 批准之后干活,返回写进卡里的结果。
    """

    name: str
    permission: str
    cost: str
    summarize: Callable[[Session, dict[str, Any]], str]
    execute: Callable[[Session, Any, str | None], dict[str, Any]]
    validate: Callable[[Session, str, dict[str, Any]], None] | None = None
    #: 这次调用实际属于哪一档 —— 返回更高的那一档,或 None 表示就按声明的来。
    #: 静态表说不清后果:同一个 edit_workflow,加一个文本节点和加一个 code 节点不是一回事。
    escalate: Callable[[Session, str, dict[str, Any]], str | None] | None = None

    def __post_init__(self) -> None:
        if self.permission not in PERMISSIONS or self.cost not in COSTS:
            raise ValueError(f"{self.name}:权限/开销档次不认识")


_TOOLS: dict[str, ConfirmableTool] = {}


def confirmable_tool(tool: ConfirmableTool) -> ConfirmableTool:
    if tool.name in _TOOLS:
        raise ValueError(f"重复登记的确认卡工具:{tool.name}")
    _TOOLS[tool.name] = tool
    return tool


def tool_spec(name: str) -> ConfirmableTool | None:
    return _TOOLS.get(name)


def tool_specs() -> dict[str, ConfirmableTool]:
    return dict(_TOOLS)
