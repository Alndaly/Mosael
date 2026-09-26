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

import inspect
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, PresentedToken
from app.domain.permissions import ensure_workspace_member, ensure_workspace_perm
from app.core.security import find_session
# 清单本身在领域层 —— 上下文水位也要按它算"工具定义占了多少",而那段代码在 api 层之下。
from app.domain.agent.tool_manifest import PLUGIN_TOOL_PREFIX, ToolSpec, agent_tool_specs, tool_registry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent-tools"])


class ToolInvocation(BaseModel):
    arguments: dict[str, Any] = {}
    # 确认卡上显示的请求方(如 "pi-agent");留空用注册表默认("mcp-agent")。
    requested_by: str = ""
    # **没有 session_id**:这次调用属于哪次对话,由调用方的令牌说了算(见下面 set_session_id 那段)。
    # 参数说的可以是任何值,令牌不行。


@router.get("/agent/tools", response_model=list[ToolSpec])
def list_agent_tools(db: DbSession, user: CurrentUser) -> list[ToolSpec]:
    """The tools an agent runtime may offer. Derived from the MCP registry, never a second list."""
    return agent_tool_specs(db, user.id)


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


def _session_workspace(db: Any, token: str) -> str:
    """这份凭据所属那次对话的工作区。没有会话(登录令牌、MCP 直连)就是空串。"""
    from app.db.models import AgentSession

    auth = find_session(db, token)
    session = db.get(AgentSession, auth.agent_session_id) if auth is not None and auth.agent_session_id else None
    return session.workspace_id if session is not None else ""


def _invoke_plugin_tool(
    db: Any, name: str, body: ToolInvocation, user: Any, token: str, workspace_id: str = ""
) -> dict[str, Any]:
    """把展开后的名字反查回 (连接, 工具) 并执行 —— **有后果的先开一张卡**。

    后果由工具在清单里声明(domain/effects):none 就地跑,走的是 invoke 这条**唯一**的插件执行
    路径 —— 权限校验、凭据注入、调用留痕都在那里,智能体不该有一条自己的捷径。花钱的、对外的、
    在本机跑代码的开一张以这个工具命名的卡(domain/agent/confirmable/plugin_tools),回包和内置的
    确认类工具一个形状 {confirmation_id, status: pending, …};批准之后走的还是同一个 invoke。

    工作区:参数给了用参数(上面已经过了 ensure_workspace_member),没给就用这份凭据那次对话的 ——
    sidecar 不带这个参数,而卡总得开在某个工作区里,插件交出的文件也要收进它的素材库。
    """
    from app.api.routes.confirmations import open_confirmation
    from app.domain.agent.confirmable.plugin_tools import exposed_tool
    from app.domain.effects import needs_card
    from app.domain.plugins import PluginDomainError
    from app.domain.plugins.tools import invoke

    match = exposed_tool(db, name, user.id)
    if match is None:
        # 连接被停用/撤权/凭据被清空、或者这个工具被取消暴露之后,模型手里还攥着上一轮的
        # 工具表。说清楚是哪一类问题,而不是一句"找不到"。
        raise HTTPException(status_code=404, detail=tr("routeErr_pluginToolUnavailable", name=name))
    workspace_id = workspace_id or _session_workspace(db, token)
    if needs_card(match["effects"]):
        if not workspace_id:
            raise HTTPException(status_code=422, detail=tr("routeErr_pluginToolNeedsWorkspace", name=name))
        # 开卡是写操作,和 POST /api/confirmations 同一道闸。
        ensure_workspace_perm(db, user, workspace_id, "edit")
        confirmation = open_confirmation(
            db, user, token, workspace_id=workspace_id, tool=name, payload={"arguments": dict(body.arguments)},
            requested_by=body.requested_by or "external-agent",
        )
        return {"result": tool_registry()._confirmation_reply({
            "id": confirmation.id,
            "status": confirmation.status,
            "permission": confirmation.permission,
            "summary": confirmation.summary,
        })}
    if workspace_id:
        # 和插件页「试一下」同一道闸:带着工作区跑的插件工具会读它的素材、把产出收进它的素材库。
        # 此前这里只查「是不是成员」—— 只读成员经 MCP 直连带上工作区 id,就能往里写素材
        # (effects: none 的工具不开卡,「收进素材库」正是 none)。
        ensure_workspace_perm(db, user, workspace_id, "edit")
    try:
        invocation = invoke(db, match["instance_id"], match["name"], body.arguments, workspace_id=workspace_id or None)
    except PluginDomainError as exc:
        return {"error": str(exc)[:500]}
    if invocation.status != "succeeded":
        return {"error": (invocation.error or tr("routeErr_pluginCallFailed"))[:500]}
    return {"result": invocation.output}


@router.post("/agent/tools/{name}")
def invoke_agent_tool(
    name: str,
    body: ToolInvocation,
    db: DbSession,
    user: CurrentUser,
    token: PresentedToken,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Run one registered tool as the calling user.

    The runtime does not need to know how a tool is implemented — that knowledge living in two
    places is what caused the drift this module exists to end.
    """
    if workspace_id:
        ensure_workspace_member(db, user, workspace_id)
    if name.startswith(PLUGIN_TOOL_PREFIX):
        return _invoke_plugin_tool(db, name, body, user, token, workspace_id)
    registry = tool_registry()
    fn = getattr(registry, name, None)
    if fn is None or not callable(fn) or name.startswith("_"):
        raise HTTPException(status_code=404, detail=f"Tool {name} not found")

    from app.core.config import settings

    # 这次调用属于哪次对话:从**令牌**取,不从参数取。turn 令牌铸造时就带着它
    # (core/security.mint_service_session),而参数是调用方自己填的 —— 填上别人的会话 id 就能把
    # 计划写进别人的对话。
    auth = find_session(db, token)
    arguments, dropped = _fit_arguments(fn, body.arguments)
    if dropped:
        # 丢了什么要留痕:静默容错在排查时会变成"参数明明传了却没生效"。
        logger.info("tool %s: dropped unsupported arguments %s", name, dropped)
    # 工具体回连本 API,所以要带调用方的凭据 —— 用**调用方这次带进来的那份**,不另铸一个
    # (此前每次调用铸一行永久的 AuthSession)。地址用本进程自己的,不靠导入期默认的 8800。
    with registry.calling_as(
        token=token,
        api_base=f"http://{settings.backend_host}:{settings.backend_port}",
        requested_by=body.requested_by,
        session_id=(auth.agent_session_id if auth is not None else None) or "",
    ):
        try:
            result = fn(**arguments)
        except TypeError as exc:  # 缺必填参数(含把参数名拼错的情况)—— 是模型的输入问题,不是服务端故障
            accepted = ", ".join(_accepted_names(fn)) or tr("routeErr_toolArgsNone")
            raise HTTPException(status_code=422, detail=tr("routeErr_toolBadArgs", detail=str(exc), accepted=accepted)) from exc
        except Exception as exc:  # noqa: BLE001 — a failing tool is a result, not a 500
            logger.warning("tool %s failed: %s", name, exc)
            return {"error": str(exc)[:500]}
    return _as_payload(result)


def _as_payload(result: Any) -> dict[str, Any]:
    """工具的返回值 → 这条 HTTP 通道的形状。

    多数工具返回普通数据,原样放进 `result`。**会给模型看图的工具**返回 MCP 标准内容块
    (文字 + 图片,见 mcp_server._with_images):文字解析回数据进 `result`,图片单独放进
    `images`,由 sidecar 交给模型当视觉输入。只有这一种形状,不按工具名特判。
    """
    from mcp.types import ImageContent, TextContent

    if not (isinstance(result, list) and result and all(isinstance(b, (TextContent, ImageContent)) for b in result)):
        return {"result": result}
    text = "\n".join(block.text for block in result if isinstance(block, TextContent))
    try:
        value: Any = json.loads(text)
    except ValueError:
        value = text
    images = [{"mime_type": b.mime_type, "data": b.data} for b in result if isinstance(b, ImageContent)]
    return {"result": value, "images": images}
