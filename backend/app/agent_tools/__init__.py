"""智能体的工具,按族分模块。导入这个包 = 把全部工具登记进 `domain/agent/tools/catalog`(`app.main` 启动时导入一次)。

族的顺序就是发给模型的工具顺序:先看、点电脑,再素材与生成,最后是对话本身。新加一族在这里 import 一行。
各族怎么登记、调用时身份从哪来、怎么调领域用例,见 ./registry。
"""

from __future__ import annotations

from app.agent_tools import (  # noqa: F401 — 导入即登记
    computer,
    media,
    generation,
    knowledge,
    skills,
    host,
    browser,
    scenes,
    entities,
    plugins,
    workflows,
    conversation,
    publish,
)
from app.domain.agent.tools import catalog

#: 由每个工具的 `@tool(effect=...)` 派生。**HTTP 通道(/api/agent/tools/{name})只认登记过的**:此前它 `getattr(模块, name)`,
#: 于是模块里任何公开的可调用对象都成了登录用户能调、不经确认卡的「工具」(SEC-13)。
REGISTERED_TOOLS = frozenset(one.name for one in catalog.definitions())
CONFIRMATION_TOOLS = catalog.names(effect="confirms")
READ_ONLY_TOOLS = catalog.names(effect="reads")
MUTATING_TOOLS = catalog.names(effect="writes")
ANSWER_TOOLS = catalog.names(awaits_answer=True)
