"""确认卡工具的登记表。加一个工具 = 加一条 `ConfirmableTool`。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

#: 权限档次(plan §17.4)。"edit" 最坏也撤得回;"render-cost"/"ai-cost" 花的是时间或钱;
#: "external" 的后果在这个应用之外 —— 发出去的帖子、别人服务器上的改动、本机跑过的代码。
#:
#: "destroy" 是**在这个应用之内、但撤不回**的那一档:删素材会把文件从盘上清掉,删项目会连着
#: 它的序列一起没。挂 "edit" 是说谎(那一档的定义就是"最坏也撤得回"),挂 "external" 也不对
#: (后果就在这个应用里)。自成一档之后,自动放行里它和 external 走同一条路 —— 没有可枚举的
#: 放行判据,一律回到人。
#: 一条卡上的话:**(文案 key, 参数)**。参数里可以再嵌 `fragment(...)`(见 core/i18n)——
#: 摘要是拼出来的,拼进去的每一段自己也是文案,当场翻的话内层还是冻成了写它那天的语言。
Summary = tuple[str, dict[str, Any]]

PERMISSIONS = ("edit", "destroy", "render-cost", "ai-cost", "external")
COSTS = ("none", "render", "ai")


@dataclass(frozen=True)
class ConfirmableTool:
    """一个会改东西的工具:开卡前怎么校验、卡上怎么说、批准之后做什么。

    - `validate(db, workspace_id, payload)` —— 说不通的请求**在开卡之前**就拒(一张注定执行不了
      的卡没有让用户去点的道理)。可以顺手把摘要要用的事实写回 payload。
    - `summarize(db, payload)` —— 卡上那句话,返回 **(文案 key, 参数)**。说的必须是待会儿真要
      做的事。

      **返回 key 而不是句子**,是因为这一行会**落库**,而卡活得比一次请求久:写入时就翻会把
      语言冻死在那一刻,英文用户读到的授权提示永远是中文。`Job.message` 为这件事付过账并立了
      规矩(见 domain/jobs.say 那段注释:「**而那正是这次要修的毛病**」),确认卡是同一层、
      同样落库、同样给人看的另一份文案,当时没跟着改。

      **确认卡尤其不能含糊**:它是授权界面 —— 用户点「批准」之前唯一会读的就是这一行。
      一个英文用户读不懂的授权提示,等于没有提示。
    - `execute(db, confirmation, actor)` —— 批准之后干活,返回写进卡里的结果。
    """

    name: str
    permission: str
    cost: str
    summarize: Callable[[Session, dict[str, Any]], tuple[str, dict[str, Any]]]
    execute: Callable[[Session, Any, str | None], dict[str, Any]]
    validate: Callable[[Session, str, dict[str, Any]], None] | None = None
    #: 自动放行里的哪一档(`domain/agent/rules`)。空 = 这类操作没有可枚举的判据,一律回到人。
    #: **由工具自己声明**,而不是让权限领域去列一张工具名单 —— 它不该认识 Blender 是什么。
    gate: str = ""
    #: 这一档在放行理由里怎么称呼("Blender 建模")。声明了 gate 就要给。
    gate_label: str = ""
    #: 这次调用实际属于哪一档 —— 返回更高的那一档,或 None 表示就按声明的来。
    #: 静态表说不清后果:同一个 edit_workflow,加一个文本节点和加一个 code 节点不是一回事。
    escalate: Callable[[Session, str, dict[str, Any]], str | None] | None = None

    def __post_init__(self) -> None:
        if self.permission not in PERMISSIONS or self.cost not in COSTS:
            raise ValueError(f"{self.name}:权限/开销档次不认识")
        if bool(self.gate) != bool(self.gate_label):
            raise ValueError(f"{self.name}:声明了放行档就要给它一个名字(反之亦然)")


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
