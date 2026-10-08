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
from dataclasses import dataclass
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


#: 插件工具跟着它的连接替宿主做的那件事走(ADR 0044 §8):替工作台提供工作流库的那种连接(ComfyUI),它暴露给智能体的
#: 工具(列工作流、查服务、停任务、把存着的每一张工作流当成一个工具跑)属于工作台那一份 —— 在工作台以外,跑一张 ComfyUI
#: 工作流走的是 generate_image(每张存着的工作流都是那里的一个模型),不必每轮再背一遍。
_PROVIDES_KIT = {"workflow_library": "comfyui"}
#: 别的插件工具(Blender、Manim、TikHub……)是**通用插件工具**那一份:和 `canvas` 同一条,工作台以外(ADR 0044 修订
#: 2026-10-08 之二)。那里是 ComfyUI 的世界;而工作台以外的几处共用同一份内置工具,按页面再分哪一处也装不下它们。
GENERAL_PLUGIN_KIT = "plugins"
#: 往回看这段对话的多少条消息(找调过的工具、点过的名)。
_TURN_HISTORY = 200
#: 工作流名「点过名」:名字至少这么长才按出现认(ADR 0044 修订之四)。此前两个字就算 —— 「放大」「测试」「人像」这类名字被
#: 日常说话带进来,每带进一张就多背一份最多 6000 字符的定义。更短的名字只有用引号 / 书名号括起来才算(「图」、《放大》)。
_MIN_NAMED = 4
#: 短名字要这样括起来才算点名。
_NAME_QUOTES = ("「」", "『』", "《》", "“”", "‘’", '""', "''", "``")
#: 经它们点到一个插件工具(参数 `tool`:工具名、完整名字或工作流路径)也算这段对话用过它:下一轮起它自己的定义跟着发。
_POINTERS = frozenset({"plugin_tools", "run_plugin_tool"})
#: 这一轮有没发的插件工具时才发的那两个:够得着它们的路。一个都没有就不背。
ON_DEMAND_TOOLS = frozenset({"plugin_tools", "run_plugin_tool"})


@dataclass(frozen=True)
class Turn:
    """这一轮的几样事实,挑**插件工具**用(ADR 0044 修订 2026-10-08)。

    - `place`:这一轮在哪说的(places.turn_place);
    - `called`:这段对话里调过的工具名,和经 `plugin_tools` / `run_plugin_tool` 点到的(它们的 `tool` 参数);
    - `said`:这段对话里用户说的话(小写),认「点过名」(只认工作流的名字,见 `_workflow_names`)。
    """

    place: Any
    called: frozenset[str]
    said: str


def turn_of(db: Any, session: Any) -> Turn:
    from sqlalchemy import select

    from app.db.models import AgentMessage
    from app.domain.agent.places import turn_place

    rows = db.execute(
        select(AgentMessage.role, AgentMessage.content, AgentMessage.payload)
        .where(AgentMessage.session_id == session.id, AgentMessage.role.in_(("user", "assistant")))
        .order_by(AgentMessage.created_at.desc())
        .limit(_TURN_HISTORY)
    ).all()
    called: set[str] = set()
    said: list[str] = []
    for role, content, payload in rows:
        payload = payload if isinstance(payload, dict) else {}
        if role == "user":
            if not payload.get("queued"):
                said.append(str(content or ""))
            continue
        for tool in _tool_calls(payload):
            called.add(str(tool.get("name") or ""))
            args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
            if tool.get("name") in _POINTERS and isinstance(args.get("tool"), str):
                called.add(args["tool"].strip())
    return Turn(place=turn_place(db, session), called=frozenset(called - {""}), said="\n".join(said).lower())


def _tool_calls(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """一条助手消息里调过的工具(时间线里的工具 / 子工具,和老消息的 `tools`)。"""
    found = [item.get("tool") for item in payload.get("timeline") or []
             if isinstance(item, dict) and item.get("type") in ("tool", "subtool")]
    found += list(payload.get("tools") or [])
    return [one for one in found if isinstance(one, dict)]


def _workflow_names(workflow: dict[str, Any]) -> list[str]:
    """一张工作流在用户嘴里可能叫什么:它的名字(各种语言)和文件名(去掉目录和 `.json`)。"""
    name = workflow.get("name")
    names = list(name.values()) if isinstance(name, dict) else [name]
    stem = str(workflow.get("path") or "").rsplit("/", 1)[-1]
    names.append(stem[: -len(".json")] if stem.lower().endswith(".json") else stem)
    return [str(one).strip().lower() for one in names if isinstance(one, str) and one.strip()]


def _named(name: str, said: str) -> bool:
    """用户的话里点到了这个名字吗(都已小写)。够长的:中文按出现认,纯英文数字的要整词(「test」不认「testing」);
    短的:只认括起来的。"""
    if len(name) >= _MIN_NAMED:
        if name.isascii():
            return re.search(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])", said) is not None
        return name in said
    return any(f"{pair[0]}{name}{pair[1]}" in said for pair in _NAME_QUOTES)


def _on_demand(tool: dict[str, Any], kit: str) -> bool:
    """这个插件工具是不是**只在用得上时**才发完整定义:存着的工作流各一个的那种(带 `workflow`),和通用插件工具。
    ComfyUI 连接自己的那几个(列工作流、查服务、停任务)在工作台里一直发。"""
    return bool(tool.get("workflow")) or kit == GENERAL_PLUGIN_KIT


def _wanted(tool: dict[str, Any], agent_name: str, turn: Turn) -> bool:
    """一个只在用得上时才发的插件工具,这一轮发不发(ADR 0044 修订 2026-10-08):这段对话调过的(直接调,或经 `plugin_tools` /
    `run_plugin_tool` 点到);工作流工具另加画布上开着的那张、用户点过名的。"""
    from app.domain.agent.places import COMFYUI, comfy_parts

    workflow = tool.get("workflow") or {}
    path = workflow.get("path") or ""
    if {agent_name, tool["name"], *([path] if path else [])} & turn.called:
        return True
    if not workflow:
        return False
    place = turn.place
    if place is not None and place.kind == COMFYUI:
        connection, open_path, _key = comfy_parts(place.id)
        if connection == tool["instance_id"] and open_path and open_path == path:
            return True
    return any(_named(name, turn.said) for name in _workflow_names(workflow))


def _plugin_kit(db: Any, instance_id: str, cache: dict[str, str]) -> str:
    """这个连接的插件工具属于哪一份:替宿主提供工作流库的是 `comfyui`,别的是 `GENERAL_PLUGIN_KIT`。`cache` 按连接记。"""
    if instance_id not in cache:
        from app.db.models import PluginInstance
        from app.domain.plugins import instances as inst
        from app.domain.plugins.errors import PluginDomainError

        instance = db.get(PluginInstance, instance_id)
        try:
            provides = inst.manifest_for(db, instance).provides if instance is not None else []
        except PluginDomainError:
            provides = []
        cache[instance_id] = next((kit for capability, kit in _PROVIDES_KIT.items() if capability in provides),
                                  GENERAL_PLUGIN_KIT)
    return cache[instance_id]


def agent_plugin_tools(db: Any, user_id: str | None, kits: frozenset[str] | None) -> list[tuple[dict[str, Any], str]]:
    """这个人在发 `kits` 那几份的地方**进得了智能体工具表**的插件工具,和各自属于哪一份(`kits` 为 None:全部)。这一轮发出去的、
    plugin_tools / run_plugin_tool 够得着的,都从这一份里挑。

    插件说不进智能体工具表的(`agent: false`;ComfyUI 有表单的工作流,它的完整工作流 —— 给智能体的是那张表单,ADR 0045 §5)不在
    这里:工作流节点、画板、插件页照常有它,这条路也不把它绕回来(要全部参数,智能体走生成那一路、带完整工作流的模型 id)。
    """
    from app.domain.plugins.tools import exposed

    cache: dict[str, str] = {}
    found = []
    for tool in exposed(db, user_id):
        if not tool["agent"]:
            continue
        kit = _plugin_kit(db, tool["instance_id"], cache)
        if kits is None or kit in kits:
            found.append((tool, kit))
    return found


@dataclass
class _PluginTools:
    specs: list[ToolSpec]
    #: 这一轮没发、经 plugin_tools / run_plugin_tool 够得着的,按连接名数:{连接名: 几个}。
    unlisted: dict[str, int]


def _plugin_tools(
    db: Any, user_id: str | None = None, kits: frozenset[str] | None = None, turn: Turn | None = None
) -> _PluginTools:
    """这个人暴露给智能体的插件工具。`turn` 给了(一段对话里的一轮)就只发这一处的那几份里**用得上的**(见 `_on_demand`、
    `_wanted`),没发的数一个数;发出去的每一个都按同一套收紧(plugin_schema)。"""
    from app.domain.agent.plugin_schema import agent_description, agent_parameters, omitted_note
    from app.domain.effects import needs_card

    specs = []
    unlisted: dict[str, int] = {}
    for tool, kit in agent_plugin_tools(db, user_id, kits):
        name = agent_tool_name(tool["instance_id"], tool["name"])
        if turn is not None and _on_demand(tool, kit) and not _wanted(tool, name, turn):
            unlisted[tool["instance_name"]] = unlisted.get(tool["instance_name"], 0) + 1
            continue
        parameters, omitted = agent_parameters(tool["input_schema"] or {"type": "object", "properties": {}})
        # 有后果的插件工具(花钱、对外、在本机跑代码,见 domain/effects)调用时先开一张卡 ——
        # 和内置的确认类工具同一个标记、同一条等待协议(sidecar 据此阻塞轮询,见 _CONFIRMATION_PROTOCOL)。
        gated = needs_card(tool["effects"])
        # 标明出处:模型据此知道这不是内置能力,失败时该建议用户去插件页看,而不是
        # 以为 Mosael 自己坏了。实例名(「TikHub · 哔哩哔哩」)也就在这里起作用 ——
        # 同名工具来自不同连接时,模型靠它分辨。
        description = agent_description(f"[插件·{tool['instance_name']}] {tool['description']}".strip())
        if omitted:
            description = f"{description}\n\n{omitted_note(omitted)}"
        specs.append(ToolSpec(
            name=name,
            description=_describe(description, gated),
            parameters=parameters,
            confirmation=gated,
            read_only=tool["read_only"],
        ))
    return _PluginTools(specs=specs, unlisted=unlisted)


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
#:
#: **短**(维护者 2026-10-08 定的方案 A,ADR 0044 修订之四):它跟在每个开卡工具的说明末尾,工作台以外每轮五十多个工具各背一遍。
#: 此前 251 字符,压到 100 字符、意思不丢 —— 会阻塞到用户批或拒;拿到结果 = 做了;报错(拒绝、作废、执行失败,见 sidecar
#: tools.awaitConfirmation 抛的那几句)= 没做;别自己轮询。
#: 仍然写在每个工具自己的说明里(test_tool_confirmation_contract 钉着),不挪进系统提示。
_CONFIRMATION_PROTOCOL = "BLOCKS until the user approves or rejects; a result means done, an error means not done. Don't poll."


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


def kits_for(place: Any) -> frozenset[str]:
    """这一轮在哪说的,就发哪几份工具(ADR 0044 §8,工具的 `kit` 见 mcp_server.tool)。通用的(不声明 kit)哪儿都发。

    ComfyUI 工作台是另一个世界:那里要的是 ComfyUI 的图(`comfyui`),不是 Mosael 的画板和时间线(`canvas`)、也不是 Blender、
    Manim 这些通用插件工具(`GENERAL_PLUGIN_KIT`);反过来,AI Studio 和 Mosael 各页面之间串门是常事(在画板里让它建一条时间线),
    那两份不按页面拆。
    """
    from app.domain.agent.places import COMFYUI

    return frozenset({"comfyui"}) if place.kind == COMFYUI else frozenset({"canvas", GENERAL_PLUGIN_KIT})


def session_kits(db: Any, session_id: str) -> frozenset[str] | None:
    """`session_id` 那段对话这一轮发哪几份(没有对话 / 对话没了:None,全部)。工具在执行时按它认够得着的插件工具。"""
    from app.db.models import AgentSession
    from app.domain.agent.places import turn_place

    session = db.get(AgentSession, session_id) if session_id else None
    return kits_for(turn_place(db, session)) if session is not None else None


def agent_tool_specs(db: Any, user_id: str | None = None, session: Any = None) -> list[ToolSpec]:
    """同一份清单,不经 HTTP —— 上下文水位要按它算「工具定义占了多少」。

    分成两个函数而不是让水位那边再列一遍:第二份清单会漂移,而漂移后的水位仍然看起来像
    测量结果(这条路由的文档注释里记着上一次漂移的代价:子智能体静默少了十九个工具)。

    `session`:这一轮属于哪段对话。按它认出这一轮在哪说的(places.turn_place),挑工具的那几份(`kits_for`);再按这段对话
    挑只在用得上时才发的插件工具(`Turn`)。这一轮有没发的,`ON_DEMAND_TOOLS` 跟着发,`plugin_tools` 的说明里点出是哪几个连接的;
    一个没发的都没有就不发那两个。没有对话的调用方(MCP 直连、界面拉工具清单)给 None —— 全给。
    """
    registry = tool_registry()
    tools = asyncio.run(registry.mcp.list_tools())
    provided = _provided_capabilities(db, user_id)
    turn = turn_of(db, session) if session is not None else None
    kits = kits_for(turn.place) if turn is not None else None
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
        if (provided is None or registry.TOOL_NEEDS.get(tool.name, "") in provided)
        and (kits is None or registry.TOOL_KITS.get(tool.name) in (None, *kits))
    ]
    plugin = _plugin_tools(db, user_id, kits, turn)
    if turn is not None and not plugin.unlisted:
        specs = [spec for spec in specs if spec.name not in ON_DEMAND_TOOLS]
    elif plugin.unlisted:
        where = "; ".join(f"{name} ({count})" for name, count in plugin.unlisted.items())
        specs = [spec.model_copy(update={"description": f"{spec.description}\n\nNot in your list now: {where}."})
                 if spec.name == "plugin_tools" else spec for spec in specs]
    return specs + plugin.specs


def _provided_capabilities(db: Any, user_id: str | None) -> set[str] | None:
    """这个人接的插件连接提供的能力(插件清单的 `provides`),加上空串(不要什么的工具)。不知道是谁(MCP 直连)回 None:
    不裁。工具的 `needs` 见 mcp_server.tool —— 只对接了 ComfyUI 的人有用的 comfy_* 工具,没接的人每轮不发。"""
    if db is None or not user_id:
        return None
    from sqlalchemy import select

    from app.db.models import PluginInstance
    from app.domain.plugins import instances as inst
    from app.domain.plugins.errors import PluginDomainError

    provided = {""}
    for instance in db.scalars(select(PluginInstance).where(PluginInstance.owner_user_id == user_id)):
        try:
            provided.update(inst.manifest_for(db, instance).provides)
        except PluginDomainError:  # 包卸掉了:它什么都不提供
            continue
    return provided
