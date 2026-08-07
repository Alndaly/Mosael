"""智能体能用的那份工具清单 —— **一份**,不是每个入口各写一份。

由 mcp_server 的注册表派生:HTTP 那条路(GET /api/agent/tools,给 sidecar 发现工具)和上下文
水位那条路(算"工具定义每轮重发占了多少")读的是同一个函数。此前它长在 api/routes 里,于是
水位那边要么反向依赖 api 层,要么自己再列一遍 —— 而再列一遍正是这份清单存在的原因:两份手写
清单必然漂移,且漂移是静默的(sidecar 曾因此静默少了十九个工具)。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from pydantic import BaseModel


def _registry():
    # Imported lazily: mcp_server sits at the repo root rather than inside the app package, and
    # importing it at module load would make the API's startup depend on the MCP library.
    import mcp_server

    return mcp_server


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    # 确认门控标:调用该工具只会创建一张待确认卡并立刻返回 {confirmation_id, status:
    # pending}。runtime 据此生成等待逻辑(sidecar 阻塞轮询 / MCP 客户端自行 get_confirmation)
    # ——以前 sidecar 为此手写第二份工具实现,现在这是元数据。
    confirmation: bool = False
    #: 子智能体只拿只读工具。内置工具的判据就是"没有确认门" —— 会改东西的都走确认卡。
    #: 插件工具没有这个对应关系:它跑的是别人的代码,可能发请求、可能写文件,所以**默认不算只读**,
    #: 除非 manifest 在那个工具上明写 `"read_only": true`。宁可让子智能体少一个工具,也不要让它
    #: 在一次"帮我查一下"里替用户发了条微博。
    read_only: bool = False


#: 展开成一等公民之后,这两个元工具就是同一份东西的第二条路径 —— 留着只会让模型在
#: "直接调 plugin__x__y" 和 "先 list 再 invoke" 之间摇摆,而后者多烧一轮还更容易填错参数。
#: 它们仍然留在 mcp_server.py 里:走 MCP 协议的客户端(Claude CLI 等)自己不做展开,靠它们发现。
_PLUGIN_META_TOOLS = frozenset({"list_plugin_tools", "invoke_plugin_tool"})

PLUGIN_TOOL_PREFIX = "plugin__"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")


def agent_tool_name(instance_id: str, tool_name: str) -> str:
    """插件工具在智能体工具表里的名字。

    **按实例而不是按包**:同一个包的两次接入是两套工具,模型要能分辨"从 B 站取"和"从抖音取"。

    各家 API 对函数名的字符集要求都是 `[A-Za-z0-9_-]`,非法字符统一折成下划线。折叠可能撞名,
    所以调用时是反查这份清单、按折叠后的名字匹配,而不是把名字劈开再拼回 id —— 拼回去才会错。
    """
    return f"{PLUGIN_TOOL_PREFIX}{_SAFE_NAME.sub('_', instance_id)}__{_SAFE_NAME.sub('_', tool_name)}"


def _plugin_tool_specs(db: Any, user_id: str | None = None) -> list[ToolSpec]:
    from app.domain.plugins.tools import exposed

    return [
        ToolSpec(
            name=agent_tool_name(tool["instance_id"], tool["name"]),
            # 标明出处:模型据此知道这不是内置能力,失败时该建议用户去插件页看,而不是
            # 以为 Open Studio 自己坏了。实例名(「TikHub · 哔哩哔哩」)也就在这里起作用 ——
            # 同名工具来自不同连接时,模型靠它分辨。
            description=f"[插件·{tool['instance_name']}] {tool['description']}".strip(),
            parameters=tool["input_schema"] or {"type": "object", "properties": {}},
            read_only=tool["read_only"],
        )
        for tool in exposed(db, user_id)
    ]


def agent_tool_specs(db: Any, user_id: str | None = None) -> list[ToolSpec]:
    """同一份清单,不经 HTTP —— 上下文水位要按它算「工具定义占了多少」。

    分成两个函数而不是让水位那边再列一遍:第二份清单会漂移,而漂移后的水位仍然看起来像
    测量结果(这条路由的文档注释里记着上一次漂移的代价:子智能体静默少了十九个工具)。
    """
    registry = _registry()
    tools = asyncio.run(registry.mcp.list_tools())
    specs = [
        ToolSpec(
            name=tool.name,
            description=tool.description or "",
            # mcp 2.0 起字段名统一为 snake_case(原 inputSchema)。
            parameters=tool.input_schema or {"type": "object", "properties": {}},
            confirmation=tool.name in registry.CONFIRMATION_TOOLS,
            # 显式声明,不再由「有没有确认卡」推出来 —— 那个推论对浏览器动作是错的,
            # 而这个标记决定的是子智能体拿得到什么(见 mcp_server.READ_ONLY_TOOLS)。
            read_only=tool.name in registry.READ_ONLY_TOOLS,
        )
        for tool in tools
        if tool.name not in _PLUGIN_META_TOOLS
    ]
    return specs + _plugin_tool_specs(db, user_id)
