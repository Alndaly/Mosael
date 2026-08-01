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
"""

from __future__ import annotations

import asyncio
import inspect
import logging
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


class ToolInvocation(BaseModel):
    arguments: dict[str, Any] = {}
    # 确认卡上显示的请求方(如 "pi-agent");留空用注册表默认("mcp-agent")。
    requested_by: str = ""
    # 发起这次调用的智能体会话:确认卡据此只在**它自己那次对话**里内联出现。留空 = 外部智能体。
    session_id: str = ""


@router.get("/agent/tools", response_model=list[ToolSpec])
def list_agent_tools(user: CurrentUser) -> list[ToolSpec]:
    """The tools an agent runtime may offer. Derived from the MCP registry, never a second list."""
    registry = _registry()
    tools = asyncio.run(registry.mcp.list_tools())
    return [
        ToolSpec(
            name=tool.name,
            description=tool.description or "",
            # mcp 2.0 起字段名统一为 snake_case(原 inputSchema)。
            parameters=tool.input_schema or {"type": "object", "properties": {}},
            confirmation=tool.name in registry.CONFIRMATION_TOOLS,
        )
        for tool in tools
    ]


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
