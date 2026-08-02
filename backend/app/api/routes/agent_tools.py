"""One tool registry, served to whichever agent runtime is in use.

There were two. mcp_server.py defines 26 tools for the Claude CLI (which speaks MCP), and
agent-sidecar/src/tools.ts hand-wrote 7 of them again for pi (which does not). The sidecar's
list was a staged build-out — its own header says "S3: read-only set", with the rest promised
for a later slice — and it stopped there. So once pi became the default agent, it silently lost
nineteen tools, including web_search, fetch_url and edit_workflow, all of which were built,
tested and confirmed present in the MCP server while being invisible to the agent that needed
them. Nothing failed loudly; the model just called a tool that "was not found".

Two lists maintained by hand will drift, and the drift is silent, so the fix is to stop having
two. The MCP registry stays the definition. These endpoints expose it — the manifest so an agent
can discover the tools, and the invoke endpoint so it can run one without reimplementing it. A
tool added to mcp_server.py is available to every runtime with no second edit.

**插件工具也在这份清单里**,展开成一等公民(`plugin__<插件>__<工具>`),而不是留在
list_plugin_tools/invoke_plugin_tool 那两个元工具后面。理由是发现成本:元工具意味着模型要先
"想到"可能有插件能帮上忙,再花一轮去列清单,才知道参数长什么样 —— 而它想不到的时候,用户
装的插件就等于不存在。展开之后,插件工具和内置工具在模型眼里没有区别,input_schema 也直接
在手上。清单只包含**已启用、权限已授、凭据已填**的插件,所以它的长度正好是用户自己开的那些。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import ensure_workspace_member

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent-tools"])


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


class ToolInvocation(BaseModel):
    arguments: dict[str, Any] = {}
    # 确认卡上显示的请求方(如 "pi-agent");留空用注册表默认("mcp-agent")。
    requested_by: str = ""
    # 发起这次调用的智能体会话:确认卡据此只在**它自己那次对话**里内联出现。留空 = 外部智能体。
    session_id: str = ""


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


def _plugin_tool_specs(db: Any) -> list[ToolSpec]:
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
        for tool in exposed(db)
    ]


@router.get("/agent/tools", response_model=list[ToolSpec])
def list_agent_tools(db: DbSession, user: CurrentUser) -> list[ToolSpec]:
    """The tools an agent runtime may offer. Derived from the MCP registry, never a second list."""
    registry = _registry()
    tools = asyncio.run(registry.mcp.list_tools())
    specs = [
        ToolSpec(
            name=tool.name,
            description=tool.description or "",
            # mcp 2.0 起字段名统一为 snake_case(原 inputSchema)。
            parameters=tool.input_schema or {"type": "object", "properties": {}},
            confirmation=tool.name in registry.CONFIRMATION_TOOLS,
            read_only=tool.name not in registry.CONFIRMATION_TOOLS,
        )
        for tool in tools
        if tool.name not in _PLUGIN_META_TOOLS
    ]
    return specs + _plugin_tool_specs(db)


def _accepted_names(fn: Any) -> list[str]:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return []
    return [
        name
        for name, param in signature.parameters.items()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]


def _fit_arguments(fn: Any, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """把模型给的参数收敛到这个工具真正接受的那些,返回 (可用参数, 被丢掉的键)。

    **多给一个键不该让整轮白跑**。模型经常顺手加上语义正确但工具没声明的键 —— 实际见过的是
    update_plan 收到一个顶层 `status`(它的每个 step 里确实有 status,模型把它抬了一层),
    于是 `fn(**arguments)` 抛 TypeError,整次调用 422,而它想做的事完全清楚。

    但**不能一律吞掉**:把必填参数拼错也表现为"多了一个不认识的键",这时静默丢弃会让工具
    带着默认值跑起来,做的是另一件事。所以只丢多余的;丢完之后必填项缺了,照样报错 ——
    而且报的是"这个工具接受哪些参数",比一句 Python 的 TypeError 更能让模型改对。
    """
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):  # 拿不到签名就原样放行,交给下面的 TypeError 兜底
        return dict(arguments), []
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    if accepts_kwargs:
        return dict(arguments), []
    known = {
        name
        for name, param in signature.parameters.items()
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    fitted = {key: value for key, value in arguments.items() if key in known}
    dropped = [key for key in arguments if key not in known]
    return fitted, dropped


def _invoke_plugin_tool(db: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """把展开后的名字反查回 (plugin_id, tool_name) 并执行。

    走的是 invoke_plugin_tool 这条**唯一**的插件执行路径 —— 权限校验、凭据注入、调用留痕
    都在那里,智能体不该有一条自己的捷径。
    """
    from app.domain.plugins import PluginDomainError
    from app.domain.plugins.tools import exposed, invoke

    match = next((t for t in exposed(db) if agent_tool_name(t["instance_id"], t["name"]) == name), None)
    if match is None:
        # 连接被停用/撤权/凭据被清空、或者这个工具被取消暴露之后,模型手里还攥着上一轮的
        # 工具表。说清楚是哪一类问题,而不是一句"找不到"。
        raise HTTPException(status_code=404, detail=f"插件工具 {name} 不可用(连接未启用、未授权、缺凭据,或该工具未开启)")
    try:
        invocation = invoke(db, match["instance_id"], match["name"], arguments)
    except PluginDomainError as exc:
        return {"error": str(exc)[:500]}
    if invocation.status != "succeeded":
        return {"error": (invocation.error or "插件调用失败")[:500]}
    return {"result": invocation.output}


@router.post("/agent/tools/{name}")
def invoke_agent_tool(
    name: str, body: ToolInvocation, db: DbSession, user: CurrentUser, workspace_id: str = ""
) -> dict[str, Any]:
    """Run one registered tool as the calling user.

    The runtime does not need to know how a tool is implemented — that knowledge living in two
    places is what caused the drift this module exists to end.
    """
    if workspace_id:
        ensure_workspace_member(db, user, workspace_id)
    if name.startswith(PLUGIN_TOOL_PREFIX):
        return _invoke_plugin_tool(db, name, body.arguments)
    registry = _registry()
    fn = getattr(registry, name, None)
    if fn is None or not callable(fn) or name.startswith("_"):
        raise HTTPException(status_code=404, detail=f"Tool {name} not found")

    # The tool bodies call back into this API over loopback, so they need the caller's own
    # credential — bound per context, since one process serves many turns at once.
    from app.ai.agent.host import mint_tool_token

    token = mint_tool_token(db, user)
    reset = registry.set_api_token(token)
    # The tool bodies call back over loopback, and this process knows its own address. Left to
    # its import-time default the base URL is 127.0.0.1:8800, which is right only by
    # coincidence — any other port and every tool answers 401 or reaches the wrong instance.
    from app.core.config import settings

    base_reset = registry.set_api_base(f"http://{settings.backend_host}:{settings.backend_port}")
    requested_by_reset = registry.set_requested_by(body.requested_by) if body.requested_by else None
    session_reset = registry.set_session_id(body.session_id) if body.session_id else None
    arguments, dropped = _fit_arguments(fn, body.arguments)
    if dropped:
        # 丢了什么要留痕:静默容错在排查时会变成"参数明明传了却没生效"。
        logger.info("tool %s: dropped unsupported arguments %s", name, dropped)
    try:
        result = fn(**arguments)
    except TypeError as exc:  # 缺必填参数(含把参数名拼错的情况)—— 是模型的输入问题,不是服务端故障
        accepted = ", ".join(_accepted_names(fn)) or "(无)"
        raise HTTPException(status_code=422, detail=f"{exc};该工具接受的参数:{accepted}") from exc
    except Exception as exc:  # noqa: BLE001 — a failing tool is a result, not a 500
        logger.warning("tool %s failed: %s", name, exc)
        return {"error": str(exc)[:500]}
    finally:
        registry._API_TOKEN.reset(reset)
        registry._API_BASE.reset(base_reset)
        if requested_by_reset is not None:
            registry._REQUESTED_BY.reset(requested_by_reset)
        if session_reset is not None:
            registry._SESSION_ID.reset(session_reset)
    return {"result": result}
