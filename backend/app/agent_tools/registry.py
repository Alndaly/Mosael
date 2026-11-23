"""智能体工具层的骨架:登记(`tool`)、这一次调用是谁(`calling_as`)、怎么调领域用例(`use_case`)、开确认卡、回图片。

各族工具在同目录的模块里(computer、browser、media……),由 `app/agent_tools/__init__.py` 依次导入、登记进
`domain/agent/tools/catalog`。这一层是**组合层**:和 `app/api` 一样可以认识领域和出参 schema;领域反过来只认 catalog。

此前这些都在仓库根的 `mcp_server.py`(4966 行、180 个工具一个文件),它在 `app/` 外,分层测试与「导入写在顶部」的棘轮
都扫不到它;参数 schema 借 MCP 库的 `MCPServer` 生成。现在搬进来,schema 由 `parameters_schema` 用 pydantic 生成(拍板 E)。
"""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, create_model

from app.api.schemas import ConfirmationOut
from app.core.i18n import LocalizedError
from app.core.unit_of_work import unit_of_work
from app.db.models import AgentSession, User
from app.domain import members
from app.domain.agent.proposals import propose
from app.domain.agent.tools import catalog
from app.domain.agent.tools.catalog import Effect, Kit, ToolDefinition


class ToolInputError(LocalizedError, ValueError):
    """工具的入参说不通(模型读到这句话会自己改)。带文案 key(`agentToolErr_*`)。"""


class ToolCallerError(LocalizedError, RuntimeError):
    """这次调用没有身份 —— 装配错了,不是模型的错。"""


class TextContent(BaseModel):
    """工具结果里的一段文字(和 MCP 的同名内容块同形)。"""

    type: Literal["text"] = "text"
    text: str


class ImageContent(BaseModel):
    """工具结果里**模型真的看得见**的一张图:base64 数据 + 媒体类型(和 MCP 的同名内容块同形)。

    会给模型看图的工具返回 `[TextContent, ImageContent…]`,/api/agent/tools 把它翻成 `{result, images}`。
    """

    type: Literal["image"] = "image"
    data: str
    mime_type: str


def caller_workspaces() -> list[dict[str, Any]]:
    """调用人所在的工作区(和界面上的顺序一样,第一个就是默认选中的那个)。"""

    return use_case(
        lambda db, user: [{"id": ws.id, "name": ws.name, "role": role} for ws, role in members.workspaces_of(db, user.id)]
    )


def default_workspace_id() -> str:
    """没给工作区时用**这次对话所在的那个**;不在对话里(登录令牌直连)才用调用人的第一个工作区。

    此前一律取第一个:用户在第二个工作区里跟智能体说「把这两个素材删掉」,模型没带 workspace_id,
    列的、删的就都是第一个工作区 —— 而这件事没有任何迹象。对话属于哪个工作区由**令牌**认出来的会话决定
    (见 calling_as),不由参数转述。
    """
    session_id = SESSION_ID.get()
    if session_id:

        def of_session(db, user) -> str:
            session = db.get(AgentSession, session_id)
            if session is None:
                raise ToolInputError("agentToolErr_sessionGone")
            return session.workspace_id

        return use_case(of_session)
    workspaces = caller_workspaces()
    if not workspaces:
        raise ValueError("No workspace available")
    return workspaces[0]["id"]


def open_card(request: dict[str, Any]) -> dict[str, Any]:
    """开一张确认卡(直接调 domain/agent/proposals.propose,不再经 POST /api/confirmations 回连)。

    `request` 就是此前那个请求体:workspace_id / tool / requested_by / payload。卡挂在哪次对话由**凭据**
    决定(calling_as 从令牌取出的会话),不看请求体。
    """

    return use_case(
        propose,
        workspace_id=request["workspace_id"],
        tool=request["tool"],
        payload=request.get("payload") or {},
        requested_by=request.get("requested_by") or "",
        session_id=SESSION_ID.get() or None,
        tool_call_id=TOOL_CALL_ID.get() or None,
        out=ConfirmationOut,
    )


#: 每个工具**做了什么**,写在它自己的装饰器上(`@tool(effect=...)`),不再是四份手写的名单。
#:
#: 此前是 CONFIRMATION_TOOLS / READ_ONLY_TOOLS / MUTATING_TOOLS / ANSWER_TOOLS 四个 frozenset,工具定义在
#: 两千行之外,靠一条测试钉住「四份合起来覆盖全部工具」。现在 `effect` 是**必填**参数:新工具漏了声明,
#: 模块连 import 都过不去,不必等测试来抓。四个名字仍在(文件末尾由登记表派生),读它们的代码不用改。
#:
#: 三种效果:
#:
#: - "confirms":调用只会立起一张确认卡并立刻返回 {confirmation_id, status: pending}。manifest
#:   (/api/agent/tools)据此打 confirmation 标,各 runtime 统一从元数据生成等待逻辑,不再手写第二份。
#: - "reads":**真正只读**,跑完之后这个世界和跑之前一样。这个标记有两个消费者:确认门控之外,
#:   sidecar 只把只读工具交给**子智能体**(它的中间过程用户不看)。此前它是**算**出来的(「不走确认卡」
#:   = 只读),对浏览器动作是错的 —— browser_type / click / upload / evaluate 都不走确认卡(入口
#:   browser_open / browser_pool_open 走过一次),于是被算成只读交了出去,而池会话用的是用户在别人
#:   站点上的**真实登录身份**。所以改成显式声明,默认也不存在:必须写。
#: - "writes":会改东西、但**不走确认卡**。浏览器那一组在这里:每次点击都弹一张卡等于让浏览器自动化
#:   不可用,入口那张卡才是该看清的地方。但「不弹卡」不等于「只读」。
#:
#: `awaits_answer=True`:调用只立起一张选择卡(见 domain/agent/questions)。和确认卡同一个形状,但确认卡问
#: 「这件事能不能做」、可以被「本会话始终允许」自动批准,而「你要哪一个」自动回答就是让模型自己编一个;
#: 两者的超时结局也不同 —— 见 tool_manifest._ANSWER_PROTOCOL。
def tool(
    *,
    effect: Effect,
    awaits_answer: bool = False,
    description: str | None = None,
    needs: str | None = None,
    kit: Kit | None = None,
):
    """登记一个工具,连同它做了什么(见上)。`effect` 没有默认值 —— 漏写是 TypeError。

    `description` 给了就用它代替 docstring:说明要从别处**生成**的工具用(edit_timeline 的算子清单从入参模型生成)。

    `needs`:这个工具只对接了某种插件能力的人有用(插件清单 `provides` 里的名字,如 ComfyUI 的 `workflow_library`)。
    没接的人每一轮不发它的定义(见 manifest.agent_tool_specs)—— 工具定义每轮重发,一个用不上的工具也是实打实的开销。

    `kit`:工具跟着**这一轮在哪说的**走(ADR 0044 §8,见 manifest.kits_for)。不声明是通用的,哪儿都发;
    `"comfyui"` 只在 ComfyUI 工作台里发(`comfy_*`,改图的、装节点包的以后也进这一份);`"canvas"` 是改 Mosael 自家画布的那一份
    (画板、时间线、3D 场景、工作流、Blender),工作台以外哪儿都发、工作台里不发 —— 那里要的是 ComfyUI 的图。
    """
    if effect not in get_args(Effect):
        raise ValueError(f"effect must be one of {get_args(Effect)}, got {effect!r}")
    if kit is not None and kit not in get_args(Kit):
        raise ValueError(f"kit must be one of {get_args(Kit)}, got {kit!r}")

    def register(fn):
        catalog.register(
            ToolDefinition(
                name=fn.__name__,
                description=description or fn.__doc__ or "",
                parameters=parameters_schema(fn),
                effect=effect,
                awaits_answer=awaits_answer,
                needs=needs or "",
                kit=kit,
                function=fn,
            )
        )
        return fn

    return register


def parameters_schema(fn: Callable[..., Any]) -> dict[str, Any]:
    """按函数签名生成参数的 JSON Schema:每个参数一个字段,`Annotated[..., Field(description=...)]` 的说明照带,
    有默认值的是可选。模型名是 `<函数名>Arguments`(schema 里的 `title`)。

    此前借 MCP 库的 `MCPServer` 生成(拍板 E):这一层从来不是 MCP 服务,只用它这一下,而库在 2.0 改过一次名。
    生成规则照它的来,换过来前后发给模型的定义逐字相同(tests/test_agent_tool_schemas 逐个工具对照)。
    """
    fields: dict[str, Any] = {}
    for parameter in inspect.signature(fn, eval_str=True).parameters.values():
        if parameter.name.startswith("_"):
            raise TypeError(f"{fn.__name__}: parameter {parameter.name} cannot start with '_'")
        annotation = Any if parameter.annotation is inspect.Parameter.empty else parameter.annotation
        metadata: list[Any] = []
        if parameter.annotation is inspect.Parameter.empty:
            metadata.append(WithJsonSchema({"title": parameter.name, "type": "string"}))
        typed = Annotated[(annotation, *metadata, Field())]
        fields[parameter.name] = typed if parameter.default is inspect.Parameter.empty else (typed, parameter.default)
    model = create_model(f"{fn.__name__}Arguments", __config__=ConfigDict(arbitrary_types_allowed=True), **fields)
    return model.model_json_schema(by_alias=True)

# 确认卡上显示的请求方。经 /api/agent/tools 调用时由调用方标注(如 "pi-agent");没标注的用默认。
REQUESTED_BY: contextvars.ContextVar[str] = contextvars.ContextVar("mosael_requested_by", default="mcp-agent")


def set_requested_by(name: str) -> contextvars.Token:
    return REQUESTED_BY.set(name)


#: 发起本次工具调用的智能体会话 —— **由调用方的凭据认出来的**,不是它自己说的(见
#: api/routes/agent_tools 与 core/security.mint_service_session)。给 `update_plan` 用:
#: 计划写进哪次对话,同样不该由参数决定。
#:
#: 确认卡**不再**读它:归属由开卡请求自己的令牌决定(routes/confirmations)。这里少一条转述,
#: 就少一处能和令牌打架的说法。默认空串 = 没有会话(登录令牌直连等)。
SESSION_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mosael_session_id", default="")


def set_session_id(session_id: str) -> contextvars.Token:
    return SESSION_ID.set(session_id)


#: 这次调用是**谁**(用户 id)。直接调领域用例的工具据此在自己的事务里取出行动人,不再经 HTTP 回连让路由去认令牌。
CALLER_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mosael_caller_id", default="")

#: 这是那次对话里**哪一次工具调用**(运行时报的 toolCallId)。开卡时记在卡上,对话界面据此把卡摆回那一步
#: (见 ToolConfirmation.tool_call_id)。只管摆位,不管授权 —— 所以由运行时报上来也无妨。空串 = 不知道。
TOOL_CALL_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mosael_tool_call_id", default="")


def calling_as(*, user_id: str, requested_by: str = "", session_id: str = "", tool_call_id: str = ""):
    """在进程内以某个调用方的身份跑工具。几个上下文变量一起设、一起还原 —— 调用方不必知道这里有几个、叫什么。

    只有**身份**:这次调用是谁、属于哪次对话、是其中哪一次调用、谁发起的。工具体直接调领域用例,不再经 HTTP 回连,
    所以没有令牌、没有后端地址要交给它。
    """
    return _calling_as(user_id=user_id, requested_by=requested_by, session_id=session_id, tool_call_id=tool_call_id)


@contextlib.contextmanager
def _calling_as(*, user_id: str, requested_by: str, session_id: str, tool_call_id: str):
    resets = [(CALLER_ID, CALLER_ID.set(user_id))]
    if requested_by:
        resets.append((REQUESTED_BY, REQUESTED_BY.set(requested_by)))
    if session_id:
        resets.append((SESSION_ID, SESSION_ID.set(session_id)))
    if tool_call_id:
        resets.append((TOOL_CALL_ID, TOOL_CALL_ID.set(tool_call_id)))
    try:
        yield
    finally:
        for var, reset in reversed(resets):
            var.reset(reset)


def use_case(fn, *args: Any, out: Any = None, **kwargs: Any) -> Any:
    """**直接**调一个领域用例:一次工具调用一个事务,行动人就是这次调用的人,闸在用例里(见 core/unit_of_work)。

    `out`:把返回的 ORM 对象按哪个出参 schema 摊平 —— 和经 HTTP 时模型看到的是同一个形状。要在事务里摊平:
    关系属性出了会话就读不到了。领域错误原样抛出,invoke 那一层把它变成给模型看的 {"error": ...}。
    """

    caller = CALLER_ID.get()
    if not caller:
        raise ToolCallerError("agentToolErr_noCaller")
    with unit_of_work() as db:
        user = db.get(User, caller)
        if user is None:
            raise ToolCallerError("agentToolErr_callerGone")
        result = fn(db, user, *args, **kwargs)
        if out is None:
            return result
        if isinstance(result, list):
            return [out.model_validate(item).model_dump(mode="json") for item in result]
        return out.model_validate(result).model_dump(mode="json") if result is not None else None


def with_images(data: dict[str, Any]) -> list[TextContent | ImageContent]:
    """把 `data["images"]` 摘出来,变成**模型真的看得见**的图片块;其余字段留在文字里。

    返回 MCP 的标准内容块,而不是把 base64 塞进 JSON:走 MCP 协议的客户端(Claude CLI 等)
    原样收到图片;走 HTTP 的 pi sidecar 由 /api/agent/tools 翻成 `{result, images}` 再转给模型
    (见 api/routes/agent_tools._as_payload)。塞进 JSON 的话,模型读到的是几十万字符的乱码。
    """
    images = data.pop("images", []) or []
    data["image_views"] = [one.get("view", "") for one in images]
    return [
        TextContent(type="text", text=json.dumps(data, ensure_ascii=False)),
        *(ImageContent(type="image", data=one["data"], mime_type=one["mime_type"]) for one in images),
    ]


def confirmation_reply(confirmation: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmation_id": confirmation["id"],
        "status": confirmation["status"],
        "permission": confirmation["permission"],
        "summary": confirmation["summary"],
        "message": "等待用户在 Mosael 中确认。用 get_confirmation 轮询结果；批准后 result 才会填充。",
    }