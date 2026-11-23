"""智能体工具的**登记处**:每个工具叫什么、做了什么(读 / 写 / 立确认卡)、参数长什么样、调哪个函数。

工具本体在组合层 `app/agent_tools/`(它们要用接口层的出参 schema,不能住在领域里);领域里读工具清单的人
(`manifest` 拼给模型的那份、上下文水位、子智能体挑工具)只认这里。此前 `manifest` 反过来延迟 `import mcp_server`
—— 「领域 → 仓库根的模块 → 路由层」,分层测试看不见。现在依赖朝下:`app/agent_tools` 在导入时把工具登记进来,
应用启动时由 `app.main` 导入它一次。

登记处是空的就说明没人导入工具层 —— 那是装配错了,直接报错,不悄悄给模型一份空清单。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Effect = Literal["reads", "writes", "confirms"]
#: 工具属于哪一份(ADR 0044 §8):不声明的是通用的,哪儿都发。
Kit = Literal["comfyui", "canvas"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    #: 给模型看的说明(工具函数的文档串,或登记时显式给的那份)。
    description: str
    #: 参数的 JSON Schema(按函数签名生成,见 app/agent_tools/registry)。
    parameters: dict[str, Any]
    effect: Effect
    #: 调用只立起一张选择卡(见 domain/agent/questions)。
    awaits_answer: bool
    #: 只对接了这种插件能力的人才发它(插件清单 `provides` 里的名字);空 = 谁都发。
    needs: str
    kit: Kit | None
    function: Callable[..., Any]


_DEFINITIONS: dict[str, ToolDefinition] = {}


def register(definition: ToolDefinition) -> None:
    if definition.name in _DEFINITIONS:
        raise ValueError(f"tool {definition.name} registered twice")
    _DEFINITIONS[definition.name] = definition


def definitions() -> list[ToolDefinition]:
    """登记顺序(也是发给模型的顺序)。"""
    if not _DEFINITIONS:
        raise RuntimeError("no agent tools registered — app.agent_tools was never imported (app.main does that at startup)")
    return list(_DEFINITIONS.values())


def get(name: str) -> ToolDefinition | None:
    definitions()
    return _DEFINITIONS.get(name)


def names(*, effect: Effect | None = None, awaits_answer: bool | None = None) -> frozenset[str]:
    return frozenset(
        one.name
        for one in definitions()
        if (effect is None or one.effect == effect) and (awaits_answer is None or one.awaits_answer == awaits_answer)
    )
