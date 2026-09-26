"""智能体能用的那份工具清单 —— **一份**,不是每个入口各写一份。

由 mcp_server 的注册表派生:HTTP 那条路(GET /api/agent/tools,给 sidecar 发现工具)和上下文
水位那条路(算"工具定义每轮重发占了多少")读的是同一个函数。此前它长在 api/routes 里,于是
水位那边要么反向依赖 api 层,要么自己再列一遍 —— 而再列一遍正是这份清单存在的原因:两份手写
清单必然漂移,且漂移是静默的(sidecar 曾因此静默少了十九个工具)。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from pydantic import BaseModel


def tool_registry():
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
    #: 等用户作答标:调用只会立起一张选择卡并立刻返回 {question_id, status: pending}。
    #: 和 confirmation 同一个形状、同一个理由 —— 等法由 runtime 按元数据生成,而不是写进
    #: 工具描述里(写进去就必然对另一条运行时说谎)。两者的**超时结局不同**,见下面的协议段。
    awaits_answer: bool = False


#: 展开成一等公民之后,这两个元工具就是同一份东西的第二条路径 —— 留着只会让模型在
#: "直接调 plugin__x__y" 和 "先 list 再 invoke" 之间摇摆,而后者多烧一轮还更容易填错参数。
#: 它们仍然留在 mcp_server.py 里:走 MCP 协议的客户端(Claude CLI 等)自己不做展开,靠它们发现。
PLUGIN_META_TOOLS = frozenset({"list_plugin_tools", "invoke_plugin_tool"})

PLUGIN_TOOL_PREFIX = "plugin__"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_]+")

#: 函数名的长度上限:各家里最严的那个(OpenAI 兼容接口、Gemini 都是 64)。
#:
#: 连接 id 是 32 位十六进制,`plugin__<id>__` 就占了 42 个字符,留给工具名的只剩 22 个。而 MCP 服务的
#: 工具名常常更长(TikHub 的 `fetch_one_video_by_share_url`、Blender 的 `get_blendfile_summary_datablocks`)——
#: 这样的工具一勾上,**整轮请求**被供应商以「函数名太长」拒掉,智能体连一句话都回不了。
MAX_AGENT_TOOL_NAME = 64
#: 缩短时带上的指纹长度(十六进制位)。它保证缩短之后仍然一个名字对一个工具。
_NAME_DIGEST = 8


def agent_tool_name(instance_id: str, tool_name: str) -> str:
    """插件工具在智能体工具表里的名字。

    **按实例而不是按包**:同一个包的两次接入是两套工具,模型要能分辨"从 B 站取"和"从抖音取"。

    各家 API 对函数名的字符集要求都是 `[A-Za-z0-9_-]`,非法字符统一折成下划线。折叠可能撞名,
    所以调用时是反查这份清单、按折叠后的名字匹配,而不是把名字劈开再拼回 id —— 拼回去才会错。

    **不超过 MAX_AGENT_TOOL_NAME。** 放得下就是完整的 `plugin__<连接>__<工具>`(已有的名字一个不变);
    放不下时连接 id 只留前 8 位、工具名能留多少留多少,末尾接上完整名字的指纹 —— 模型仍读得出
    是哪个工具,两个工具也不会缩成同一个名字。
    """
    safe_instance = _SAFE_NAME.sub("_", instance_id)
    safe_tool = _SAFE_NAME.sub("_", tool_name)
    full = f"{PLUGIN_TOOL_PREFIX}{safe_instance}__{safe_tool}"
    if len(full) <= MAX_AGENT_TOOL_NAME:
        return full
    digest = hashlib.sha256(full.encode("utf-8")).hexdigest()[:_NAME_DIGEST]
    head = f"{PLUGIN_TOOL_PREFIX}{safe_instance[:8]}__{safe_tool}"
    return f"{head[: MAX_AGENT_TOOL_NAME - _NAME_DIGEST - 1]}_{digest}"


def _plugin_tool_specs(db: Any, user_id: str | None = None) -> list[ToolSpec]:
    from app.domain.effects import needs_card
    from app.domain.plugins.tools import exposed

    specs = []
    for tool in exposed(db, user_id):
        # 有后果的插件工具(花钱、对外、在本机跑代码,见 domain/effects)调用时先开一张卡 ——
        # 和内置的确认类工具同一个标记、同一条等待协议(sidecar 据此阻塞轮询,见 _CONFIRMATION_PROTOCOL)。
        gated = needs_card(tool["effects"])
        specs.append(ToolSpec(
            name=agent_tool_name(tool["instance_id"], tool["name"]),
            # 标明出处:模型据此知道这不是内置能力,失败时该建议用户去插件页看,而不是
            # 以为 Mosael 自己坏了。实例名(「TikHub · 哔哩哔哩」)也就在这里起作用 ——
            # 同名工具来自不同连接时,模型靠它分辨。
            description=_describe(f"[插件·{tool['instance_name']}] {tool['description']}".strip(), gated),
            parameters=tool["input_schema"] or {"type": "object", "properties": {}},
            confirmation=gated,
            read_only=tool["read_only"],
        ))
    return specs


#: 确认门控工具在**这条路**上的真实协议。工具自己的描述只说事实(要用户批准、可能花钱),
#: 不说「怎么等」—— 怎么等每条运行时都不一样,写死在描述里就必然对另一条说谎:
#:
#:   · 走 sidecar(应用自己):sidecar 建卡后**阻塞轮询**确认卡,用户批完才把**最终结果**
#:     交给模型(见 agent-sidecar/src/tools.ts)。模型从头到尾看不到 confirmation_id。
#:   · 直连 MCP(Claude CLI 等):调用立刻拿到 {confirmation_id, status: pending},自己去
#:     get_confirmation 轮询 —— 这个协议由回包里的 message 字段当场说清,不必写进描述。
#:
#: 描述里留着「after approval get_confirmation returns the job_id」的后果是真机可见的:
#: 模型按它去找一个永远收不到的 confirmation_id,在对话里说「我没有收到 confirmation_id」,
#: 然后多跑 get_job / sleep 两步去查一件已经做完的事。
_CONFIRMATION_PROTOCOL = (
    "This call BLOCKS until the user approves or rejects it, and then returns the final "
    "result directly — there is no confirmation_id for you to poll and no need to call "
    "get_confirmation or get_job afterwards. A returned result means it already happened."
)


#: 选择卡在这条路上的真实协议。和确认卡是同一件事的两个结局:
#:
#:   · 确认卡超时 = 这个动作**没有发生**,所以那边抛错。
#:   · 选择卡超时 = 用户还没顾上答,而答案**仍然会到**(用户作答后由回执送回这次对话,
#:     见 domain/agent/questions.deliver_to_session)。所以这边不抛错,如实说"还没答",
#:     让模型自己决定是按判断继续还是收尾 —— 抛错会让它以为问这件事失败了,转头再问一遍。
_ANSWER_PROTOCOL = (
    "This call BLOCKS until the user answers or skips, and then returns their answer directly "
    "— there is no question_id for you to poll and no need to call get_answer afterwards. "
    "If it returns status \"pending\" the user has not got to it yet: carry on with your own "
    "best judgement or wrap up, and do NOT ask the same thing again — their answer will arrive "
    "on its own once they do respond."
)


def _describe(description: str, gated: bool, awaits_answer: bool = False) -> str:
    if awaits_answer:
        return f"{description.rstrip()}\n\n{_ANSWER_PROTOCOL}"
    if not gated:
        return description
    return f"{description.rstrip()}\n\n{_CONFIRMATION_PROTOCOL}"


def agent_tool_specs(db: Any, user_id: str | None = None) -> list[ToolSpec]:
    """同一份清单,不经 HTTP —— 上下文水位要按它算「工具定义占了多少」。

    分成两个函数而不是让水位那边再列一遍:第二份清单会漂移,而漂移后的水位仍然看起来像
    测量结果(这条路由的文档注释里记着上一次漂移的代价:子智能体静默少了十九个工具)。
    """
    registry = tool_registry()
    tools = asyncio.run(registry.mcp.list_tools())
    specs = [
        ToolSpec(
            name=tool.name,
            description=_describe(
                tool.description or "",
                tool.name in registry.CONFIRMATION_TOOLS,
                tool.name in registry.ANSWER_TOOLS,
            ),
            # mcp 2.0 起字段名统一为 snake_case(原 inputSchema)。
            parameters=tool.input_schema or {"type": "object", "properties": {}},
            confirmation=tool.name in registry.CONFIRMATION_TOOLS,
            awaits_answer=tool.name in registry.ANSWER_TOOLS,
            # 显式声明,不再由「有没有确认卡」推出来 —— 那个推论对浏览器动作是错的,
            # 而这个标记决定的是子智能体拿得到什么(见 mcp_server.READ_ONLY_TOOLS)。
            read_only=tool.name in registry.READ_ONLY_TOOLS,
        )
        for tool in tools
        if tool.name not in PLUGIN_META_TOOLS
    ]
    return specs + _plugin_tool_specs(db, user_id)
