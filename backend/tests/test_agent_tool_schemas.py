"""智能体工具的参数 schema 由 `app/agent_tools/registry.parameters_schema` 用 pydantic 生成(拍板 E),不再借 MCP 库的
`MCPServer`。换生成器的那一刻,发给模型的工具定义一个字都不该变 —— 模型对参数的理解全靠它。

所以对每个登记过的工具,拿 MCP 库自己的生成规则(`func_metadata`)做对照。MCP 库还在后端依赖里(MCP 类插件的客户端要它),
这条对照不额外引入依赖;哪天 MCP 改了它的规则,这条红了要看的是「我们要不要跟」,而不是照抄。
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.utilities.func_metadata import func_metadata

import app.agent_tools  # noqa: F401 — 导入即登记
from app.domain.agent.tools import catalog

DEFINITIONS = catalog.definitions()


def test_every_tool_is_registered_once_with_a_description() -> None:
    names = [one.name for one in DEFINITIONS]
    assert len(names) == len(set(names))
    assert len(names) >= 150, "工具清单看起来被截断了"
    assert all(one.description.strip() for one in DEFINITIONS)


@pytest.mark.parametrize("definition", DEFINITIONS, ids=lambda one: one.name)
def test_schema_matches_the_mcp_generation_rules(definition) -> None:
    expected = func_metadata(definition.function).arg_model.model_json_schema(by_alias=True)
    assert definition.parameters == expected
