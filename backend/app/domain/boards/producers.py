"""画板上的产出者(Producer)注册表 —— 画板上「能产出东西的动作」只有这一个入口(ADR 0021)。

此前是写死的四条路:生成、念、截、写,各有一个路由、一个请求体、一块面板,挂哪块面板由前端按
item 种类猜。第五种产出(插件工具、挑过的工作流节点)想上画板,就得再开第五条路由、第五块面板。
现在四个动作是注册表里的四个内置产出者,一次运行的形状只有一个(RunRequest),路由只有一条
(`POST /api/boards/{id}/run`),面板由表单上写明的 `form.producer` 决定。

第五种产出 —— 跑一个工作流节点(插件工具、声明了能上画板的内置节点)—— 是 `node:<节点类型>`,
挂在工具格(`action`)上;它们不在这里逐个登记,而是从节点注册表里读(见 _node_producers)。

一个产出者说清五件事:

· `hosts` —— 能挂在哪些 item 种类上(画板项的 kind);
· `permission` —— 跑它要的工作区权限(ensure_workspace_perm 的操作名);
· `effects` —— 有没有花钱或对外的副作用(智能体替人跑时要不要确认卡,见 ADR 0021 决定 2);
· `form` —— 它收的表单(pydantic)。**表单在领域里校验**:第二个入口(智能体、工作流)
  跑同一个产出者时,拿到的是同一份校验,不必各自再写一遍;
· `start` —— 建任务 → 摆占位 → 起任务,返回摆好占位的画板。

跑之前的检查(dry_run)和替人写下的表单的检查(check_forms)也在这里 —— 智能体替人放工具格、
替人点运行,问的是和界面**同一张注册表**,不另写一份「什么能跑、什么能接」。

四个内置的本体仍在 `actions`(`*_on_board`),这里只把它们登记成同一种东西。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.ai.providers.contracts.generation import FIRST_FRAME, SOURCE_ROLES
from app.db.models import Board
from app.domain.boards.actions import (
    BoardInputError,
    Slot,
    generate_on_board,
    speak_on_board,
    trim_on_board,
    write_on_board,
)
from app.domain.boards.canvas import BoardDomainError
from app.domain.boards.producer_ids import BUILTIN_PRODUCER_IDS, NOTE_PRODUCER, node_producer_id, node_type_of


class ProducerFailed(BoardDomainError):
    """产出者自己那一侧没做成(生成校验、模型调用、音色、截取范围)。

    带着原错误的 key 和参数(见 LocalizedError.relay),翻成哪种状态码由产出者声明 ——
    「请求本身说不通」和「上游这一次没处理成」对调用方意味着不同的下一步。
    """

    status = 400


class ProducerFormInvalid(BoardDomainError):
    """表单不合这个产出者的形状。`errors` 是 pydantic 的逐字段报错(路由照请求体校验失败回 422)。"""

    def __init__(self, producer: str, errors: list[dict[str, Any]]) -> None:
        first = errors[0] if errors else {}
        field = ".".join(str(part) for part in first.get("loc", ())) or "form"
        super().__init__("boardErr_producerFormInvalid", producer=producer, field=field, detail=str(first.get("msg", "")))
        self.errors = errors


@dataclass(frozen=True)
class RunRequest:
    """在画板上跑一次产出者:落在哪张板的哪一格、谁在跑、表单是什么。"""

    workspace_id: str
    board_id: str
    item_id: str
    #: 宿主那一格的种类。必须是产出者声明过的 hosts 之一。
    kind: str
    x: float
    y: float
    #: 调用方看到的画板版本。**在花钱之前**问(见 actions._ensure_slot_ready)。
    base_revision: int
    actor_id: str
    producer: str
    form: dict[str, Any]

    @property
    def slot(self) -> Slot:
        return Slot(self.board_id, self.item_id, self.x, self.y, self.base_revision)


@dataclass(frozen=True)
class Producer:
    """一个产出者。字段的意思见模块开头那一段。"""

    id: str
    hosts: tuple[str, ...]
    permission: str
    #: 词表见 domain/effects(none / paid / external / local-code)—— 智能体替人跑时,不是 none 的要确认卡
    #: (ADR 0021 决定 2)。
    effects: str
    form: type[BaseModel]
    start: Callable[[Session, RunRequest, Any], Board]
    #: 产出者那一侧会抛的领域错误,以及它们翻成的状态码(见 ProducerFailed)。
    failures: tuple[type[Exception], ...] = ()
    failure_status: int = 400
    #: 给界面看的描述,形状同 NODE_TYPES 的一条(标签和说明是 i18n key,出口才翻,见 describe)。
    #: 工具格的节点就是那个节点自己的条目;内置的四个只有名字和一句说明(它们的面板是专门写的)。
    meta: dict[str, Any] | None = None
    #: 能不能挑来填一个**空槽**(hosts 里那几种格子刚放下、还没有产出时)。一种格子有两个这样的
    #: 产出者时(音频槽:念一段 / 生成音乐音效),面板上给一个切换。截一段不是 —— 它得先有一段素材。
    fills_empty_slot: bool = False
    #: 起任务之前的那几样检查,**不写任何东西**(见 dry_run);返回给确认卡看的事实(用哪条连接)。
    #: 没有就只做注册表那几样(认产出者、问宿主、校验表单)。
    preflight: Callable[[Session, RunRequest, Any], dict[str, Any]] | None = None


class _Form(BaseModel):
    """产出者表单的基类。和接口层的 ApiModel 同一条规矩:**不收 NaN / Infinity**。"""

    model_config = ConfigDict(allow_inf_nan=False)


class SourceRef(_Form):
    """生成时挂进槽位的一份素材及其用途。角色取值由生成契约给(见 contracts.generation)。"""

    asset_id: str = Field(min_length=1, max_length=64)
    role: str = Field(default=FIRST_FRAME, pattern=f"^({'|'.join(SOURCE_ROLES)})$")


class GenerateForm(_Form):
    #: 发给模型的那句提示词(可带运行时追加的图例)。可以空着:要不要写由模型的描述符说(`prompt`),
    #: 生成漏斗判 —— 放大这类不收提示词的模型本来就不该有。
    prompt: str = ""
    provider: str = ""
    provider_profile_id: str = ""
    model: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: 发出去的输入素材:槽位挂的 + 正文里 @ 到的。
    source_assets: list[SourceRef] = Field(default_factory=list)
    #: 落在这一格上、用户可再次编辑的表单 —— 不含运行时追加的图例;槽位只是槽位那一半。
    item_form: dict[str, Any] = Field(default_factory=dict)


class WriteForm(_Form):
    prompt: str
    provider_profile_id: str = ""
    model: str = ""
    #: 让模型看着写的素材(上游连过来的 + 正文里 @ 到的)。
    source_assets: list[str] = Field(default_factory=list)
    #: 上游便签给的材料。
    context: list[str] = Field(default_factory=list)


class SpeakForm(_Form):
    text: str
    #: 克隆音色(配音库里那一行)。和下面的引擎音色**二选一**。
    voice_id: str = ""
    #: 引擎音色:用现成的嗓子,不必先克隆。留空则走克隆那条(voice_id)。
    engine: str = ""
    engine_voice: str = ""
    engine_voice_resource: str = ""
    speed: float = 1.0


class TrimForm(_Form):
    asset_id: str
    start: float = 0
    end: float
    mute: bool = False


def _start_generate(db: Session, request: RunRequest, form: GenerateForm) -> Board:
    return generate_on_board(
        db,
        workspace_id=request.workspace_id,
        slot=request.slot,
        actor_id=request.actor_id,
        kind=request.kind,
        prompt=form.prompt,
        provider=form.provider,
        provider_profile_id=form.provider_profile_id,
        model=form.model,
        parameters=dict(form.parameters),
        source_assets=[one.model_dump() for one in form.source_assets],
        form=dict(form.item_form),
    )


def _start_write(db: Session, request: RunRequest, form: WriteForm) -> Board:
    return write_on_board(
        db,
        workspace_id=request.workspace_id,
        board_id=request.board_id,
        item_id=request.item_id,
        actor_id=request.actor_id,
        prompt=form.prompt,
        provider_profile_id=form.provider_profile_id,
        model=form.model,
        source_asset_ids=list(form.source_assets),
        context=list(form.context),
        base_revision=request.base_revision,
    )


def _start_speak(db: Session, request: RunRequest, form: SpeakForm) -> Board:
    from app.domain.voices.engine_catalog import CLONE_ENGINE, synthesis_params

    engine = form.engine.strip() or CLONE_ENGINE
    # 引擎音色和克隆音色两条都要能走(此前只传 voice_id,画板配音只认克隆音色)。
    synthesis = synthesis_params(
        db,
        engine=engine,
        voice=form.voice_id if engine == CLONE_ENGINE else form.engine_voice,
        speed=form.speed,
        user_id=request.actor_id,
        workspace_id=request.workspace_id,
        engine_voice_resource=form.engine_voice_resource,
    )
    return speak_on_board(
        db,
        workspace_id=request.workspace_id,
        slot=request.slot,
        actor_id=request.actor_id,
        text=form.text,
        synthesis=synthesis,
        voice_id=form.voice_id,
        #: 表单照面板的形状记:克隆那条 engine 留空(不是 CLONE_ENGINE)。
        engine=form.engine.strip(),
        engine_voice=form.engine_voice,
    )


def _start_trim(db: Session, request: RunRequest, form: TrimForm) -> Board:
    return trim_on_board(
        db,
        workspace_id=request.workspace_id,
        slot=request.slot,
        actor_id=request.actor_id,
        asset_id=form.asset_id,
        start=form.start,
        end=form.end,
        mute=form.mute,
    )


def _builtin_meta(producer_id: str) -> dict[str, Any]:
    """内置产出者给界面的那一点描述:名字和一句说明(i18n key)。没有字段声明 —— 它们的面板是专门写的。"""
    return {
        "label": f"boardProducer_{producer_id}",
        "description": f"boardProducer_{producer_id}_desc",
        "category": "",
        "config": {},
        "outputs": [],
    }


def _builtins() -> dict[str, Producer]:
    """四个内置产出者。**导入期不碰这些领域** —— 生成、配音、截取各自的模块很重,且会回头
    认识画板;错误类型在这里才取。"""
    from app.domain.ai_chat import AiChatError
    from app.domain.boards.trim import TrimError
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.resolution import KINDS as GENERATION_KINDS
    from app.domain.voices.voices import VoiceError

    return {
        one.id: one
        for one in (
            Producer(
                id="generate",
                meta=_builtin_meta("generate"),
                fills_empty_slot=True,
                #: 由生成目录实际认的种类推出,不在画板这边写死一份。插件的生成模型也走同一张目录
                #: (ADR 0020),目录多认一种,画板上那种格子就能挂生成。
                hosts=tuple(GENERATION_KINDS),
                permission="edit",
                effects="paid",
                form=GenerateForm,
                start=_start_generate,
                failures=(GenerationDomainError,),
            ),
            Producer(
                id="write",
                meta=_builtin_meta("write"),
                fills_empty_slot=True,
                hosts=("note",),
                permission="ai",
                effects="paid",
                form=WriteForm,
                start=_start_write,
                failures=(AiChatError,),
                failure_status=422,
            ),
            Producer(
                id="speak",
                meta=_builtin_meta("speak"),
                fills_empty_slot=True,
                hosts=("audio",),
                permission="edit",
                effects="paid",
                form=SpeakForm,
                start=_start_speak,
                failures=(VoiceError,),
                failure_status=422,
            ),
            Producer(
                id="trim",
                meta=_builtin_meta("trim"),
                hosts=("video", "audio"),
                permission="edit",
                #: 本机 ffmpeg 截一段,不花钱、不出门。
                effects="none",
                form=TrimForm,
                start=_start_trim,
                failures=(TrimError,),
            ),
        )
    }


def list_producers(db: Session, actor_id: str | None) -> list[Producer]:
    """`actor_id` 这个人在画板上能用的全部产出者:四个内置的,加上工具格能跑的节点(见 _node_producers)。

    **每次现取** —— 插件工具随他接了什么、勾了什么而变,不能缓存成进程内状态。
    """
    return list(_registry(db, actor_id).values())


def _registry(db: Session, actor_id: str | None) -> dict[str, Producer]:
    return {**_builtins(), **_node_producers(db, actor_id)}


def get_producer(db: Session, producer_id: str, actor_id: str | None) -> Producer:
    """按 id 取产出者;没有就说清楚为什么 —— 尤其是插件工具:「你没有这个插件的连接」和「没这回事」
    是两句话,前者要告诉他去哪儿建。"""
    registry = _registry(db, actor_id)
    wanted = str(producer_id or "").strip()
    producer = registry.get(wanted)
    if producer is not None:
        return producer
    node_type = node_type_of(wanted)
    if node_type is not None:
        _explain_missing_node(db, node_type, actor_id)
    raise BoardInputError("boardErr_unknownProducer", producer=producer_id, producers=", ".join(BUILTIN_PRODUCER_IDS))


def _explain_missing_node(db: Session, node_type: str, actor_id: str | None) -> None:
    """一个工具格的节点此刻跑不了:说清是哪一种情况。总是抛。"""
    from sqlalchemy import select

    from app.db.models import PluginInstance, PluginPackage
    from app.domain.plugins.nodes import parse_node_type
    from app.domain.plugins.tools import all_tools, exposed

    parsed = parse_node_type(node_type)
    if parsed is None:
        raise BoardInputError("boardErr_nodeNotOnBoard", node=node_type)
    package_id, tool_name = parsed
    package = db.get(PluginPackage, package_id)
    mine = db.scalars(
        select(PluginInstance).where(PluginInstance.package_id == package_id, PluginInstance.owner_user_id == (actor_id or ""))
    ) if package is not None else []
    for instance in mine:
        if any(tool["name"] == tool_name and tool["internal"] for tool in all_tools(db, instance)):
            #: 只给宿主调的工具(生成协议那一类):画布上存着也不跑(和工作流里同一条)。
            raise BoardInputError("boardErr_toolInternal", tool=tool_name)
    mine_exposed = [tool for tool in exposed(db, actor_id) if tool["package_id"] == package_id
                    and tool["name"] == tool_name] if actor_id else []
    if actor_id and mine_exposed:
        from app.domain.boards.plugin_references import generation_index, mirrored_model
        from app.domain.boards.transforms import content_transform_gap
        from app.domain.plugins.nodes import node_meta

        index = generation_index(db, actor_id)
        for tool in mine_exposed:
            row = mirrored_model(index, str(tool.get("instance_id") or ""), tool.get("mirrors"))
            if row is not None and content_transform_gap(node_meta(tool), generation_has=lambda _: True) == "mirrored_by_generation":
                #: 他用得上的那个生成模型就是这件事:画板上放一格那种素材、选那个模型(见 plugin_references ——
                #: 存着的这种工具格会被对账改写成生成格,还没改到的这一格在这里说清楚)。
                raise BoardInputError("boardErr_toolMirroredByGeneration", tool=str(tool.get("label") or tool_name),
                                      model=str(row.display_name or row.model_id))
        #: 他接着这个插件、工具也开着,只是它不是一个内容变换(列清单、看状态、上传……)——
        #: 这不是「去插件页建连接」能解决的事,是「这件事在工作流里做」。清单会变(ComfyUI 的工具随
        #: 服务器上的工作流),所以画布上存着一个此刻不合格的工具格是正常的,跑的时候说清楚。
        raise BoardInputError("boardErr_toolNotOnBoard", tool=tool_name)
    raise BoardInputError("boardErr_pluginNotConnected", plugin=package.name if package is not None else package_id,
                          tool=tool_name)


class BindingRef(_Form):
    """绑定的一条:这个字段的值从上游哪一格来。"""

    model_config = ConfigDict(allow_inf_nan=False, populate_by_name=True)

    source: str = Field(alias="from", min_length=1, max_length=128)


class NodeForm(_Form):
    """工具格的表单:节点配置(键是节点声明的字段)+ 哪些字段接上游。

    配置的逐字段校验归节点自己(执行器、check_number_fields)—— 插件节点的字段是运行时才知道的,
    在这里写一份 pydantic 等于第二份声明。
    """

    config: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, list[BindingRef]] = Field(default_factory=dict)


def _node_producers(db: Session, actor_id: str | None) -> dict[str, Producer]:
    """工具格能跑的节点。两个来源,**都从节点注册表里读**,画板这边不列清单;两个来源过**同一条**
    规矩 —— 画板上只放内容变换(boards.transforms.is_content_transform,ADR 0021 修订):

    · 内置节点里声明了 `"surfaces": [..., "board"]` 的(见 workflows.NODE_TYPES 上方的说明);
    · **这个人自己**接的、可用的插件连接暴露的工具(plugins.tools.exposed,已经跳过只给宿主调的),
      按它声明的输出判:列清单、看状态、上传这类不交出内容的工具不上画板;声明了 `mirrors`、而他在生成目录里
      用得上那个模型的也不上 —— 画板上那件事走生成(一个概念一个入口,transforms 的 mirrored_by_generation)。
      同一个包接了两条连接,节点只有一个 —— 用哪条是表单里的 instance_id,运行时按人解析。
      没有执行者(None)就不列插件:「不按人过滤」只给后台无人路径用,画板上总有一个点运行的人。
    """
    from app.domain.boards.transforms import is_content_transform
    from app.domain.workflows import NODE_TYPES

    out: dict[str, Producer] = {}
    for node_type, meta in NODE_TYPES.items():
        if "board" in (meta.get("surfaces") or ()) and is_content_transform(meta):
            #: 声明了后果在应用之外的要确认卡;其余在本机做完。
            out[node_producer_id(node_type)] = _node_producer(node_type, meta, "external" if meta.get("external") else "none")
    if actor_id:
        from app.domain.plugins.nodes import node_meta, node_type_id
        from app.domain.plugins.tools import exposed

        tools = exposed(db, actor_id)
        generation = _mirror_check(db, actor_id, tools)
        for tool in tools:
            node_type = node_type_id(tool["package_id"], tool["name"])
            meta = node_meta(tool)
            if node_producer_id(node_type) not in out and is_content_transform(meta, generation_has=generation(tool)):
                #: 后果就是插件工具自己那一个(plugins.tools.all_tools 按清单算好的,见 domain/effects)——
                #: 智能体在对话里直接调它、在画板上替人点运行,问不问人是同一条规矩。
                out[node_producer_id(node_type)] = _node_producer(node_type, meta, tool["effects"])
    return out


def _mirror_check(db: Session, actor_id: str, tools: list[dict[str, Any]]) -> Callable[[dict[str, Any]], Any]:
    """工具 → 「他在生成目录里用得上这个工具声明的那个模型吗」(给 transforms.content_transform_gap)。

    生成目录只问一次(按声明里出现的种类),不是每个工具问一次 —— ComfyUI 一台服务器上百张工作流。
    模型得是**同一个连接**下的(工具报自哪个连接,模型就得出自那条连接的生成目录)。
    """
    from app.domain.boards.plugin_references import generation_index, mirrored_model

    kinds = {str(tool["mirrors"].get("kind")) for tool in tools if isinstance(tool.get("mirrors"), dict)}
    index = generation_index(db, actor_id, kinds) if kinds else {}

    def check(tool: dict[str, Any]) -> Callable[[dict[str, Any]], bool]:
        return lambda mirror: mirrored_model(index, str(tool.get("instance_id") or ""), mirror) is not None

    return check


def _node_producer(node_type: str, meta: dict[str, Any], effects: str) -> Producer:
    from app.domain.notes import NoteDomainError
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.workflows import WorkflowDomainError

    def bindings_of(form: NodeForm) -> dict[str, list[dict[str, str]]]:
        return {field: [{"from": ref.source} for ref in refs] for field, refs in form.bindings.items()}

    def start(db: Session, request: RunRequest, form: NodeForm) -> Board:
        from app.core.i18n import get_current_locale, t
        from app.domain.boards.tools import run_node_on_board

        return run_node_on_board(
            db,
            request=request,
            node_type=node_type,
            meta=meta,
            config=dict(form.config),
            bindings=bindings_of(form),
            #: 任务中心里这一条叫什么(节点的名字)。
            label=t(str(meta.get("label") or node_type), get_current_locale()),
        )

    def preflight(db: Session, request: RunRequest, form: NodeForm) -> dict[str, Any]:
        from app.db.models import PluginInstance
        from app.domain.boards.tools import prepare_node_run
        from app.domain.plugins.nodes import parse_node_type

        _board, resolved = prepare_node_run(db, request=request, node_type=node_type, meta=meta,
                                            config=dict(form.config), bindings=bindings_of(form))
        #: 插件工具用的是**这个人**自己的哪条连接(prepare 已经按人解析好了)。
        plugin = parse_node_type(node_type) is not None
        instance = db.get(PluginInstance, str(resolved.get("instance_id") or "")) if plugin else None
        return {"connection": instance.name if instance is not None else ""}

    return Producer(
        id=node_producer_id(node_type),
        hosts=("action",),
        permission="edit",
        effects=effects,
        form=NodeForm,
        start=start,
        #: 起任务之前就会失败的那几种(见 boards.tools.run_node_on_board):插件连接、数字字段、绑定的文档。
        failures=(WorkflowDomainError, PluginDomainError, NoteDomainError),
        meta=meta,
        preflight=preflight,
    )


def describe(db: Session, actor_id: str | None, locale: str) -> list[dict[str, Any]]:
    """给界面的产出者清单(`GET /api/boards/producers`):每个产出者的节点描述(和工作流节点面板
    **同一份** describe_node_types,标签、分组、字段声明一个字都不差)加上画板自己的几样 ——
    挂在哪(hosts)、要什么权限、有没有外部后果、能不能挑来填一个空槽。

    每个配置字段多一样 `board_sources`:它能接哪几种上游格子(见 boards.tools.bindable_kinds)。
    面板照它列绑定,不在前端另写一套「什么能接什么」。

    工具格(`node:*`)的描述是**画板的那一份**,不照搬工作流的(boards.transforms):字段只留创作者
    看得懂的(映射、原始 JSON、代码不出现,模板字段是一段字);`board_group` / `board_group_label` 说
    它在「添加」菜单里归哪一组(按吃什么内容分,不是工作流面板的「流程 / 数据 / AI」),
    `board_description` 是给创作者看的一句说明。工具按分组排好,组内保持注册表的顺序。
    """
    from app.core.i18n import t
    from app.domain.boards.tools import bindable_kinds
    from app.domain.boards.transforms import BOARD_GROUPS, board_config_view, board_description, board_group, content_outputs
    from app.domain.workflows.node_catalog import describe_node_types

    registry = _registry(db, actor_id)
    metas = {
        producer.id: {
            **(producer.meta or {}),
            "config": {
                key: {**spec, "board_sources": bindable_kinds(key, spec)} if isinstance(spec, dict) else spec
                for key, spec in ((producer.meta or {}).get("config") or {}).items()
            },
        }
        for producer in registry.values()
    }
    described = describe_node_types(metas, locale)
    by_id = {entry["type"]: entry for entry in described}
    groups = {producer.id: board_group(producer.meta or {}) for producer in registry.values() if node_type_of(producer.id)}
    tools = sorted((entry["type"] for entry in described if entry["type"] in groups),
                   key=lambda producer_id: BOARD_GROUPS.index(groups[producer_id]))
    ordered = [producer.id for producer in registry.values() if producer.id not in groups] + tools
    out = []
    for producer_id in ordered:
        producer = registry[producer_id]
        entry = dict(by_id[producer_id])
        node_type = node_type_of(producer_id)
        board: dict[str, Any] = {}
        if node_type is not None:
            group = groups[producer_id]
            board = {
                "config": board_config_view(entry["config"]),
                "board_group": group,
                "board_group_label": t(f"boardToolGroup_{group}", locale),
                "board_description": board_description(producer.meta or {}, locale),
                "board_products": content_outputs(producer.meta or {}),
            }
        out.append({
            **entry,
            **board,
            #: `type` 是节点类型(字段选项接口认的是它);`id` 是产出者的名字(存在表单上、跑的时候发的是它)。
            "type": node_type or producer_id,
            "id": producer_id,
            "hosts": list(producer.hosts),
            "permission": producer.permission,
            "effects": producer.effects,
            "fills_empty_slot": producer.fills_empty_slot,
        })
    return out


def producer_for_new_slot(kind: str) -> str | None:
    """新放下的一格(还没有产出)挂哪个产出者。便签写字、音频念、图片/视频生成;别的种类不产出。

    这是**新建时的缺省**,不是读的时候猜:它写进 `form.producer` 之后就是那一格自己的事实,
    改换产出者(工具格、音频槽在念和生成之间切换)也只改那一个字段。和前端 boardItemState.newSlotForm 同一张表。
    """
    if kind == "note":
        return NOTE_PRODUCER
    if kind == "audio":
        return "speak"
    generate = _builtins()["generate"]
    return generate.id if kind in generate.hosts else None


def _admit(db: Session, request: RunRequest) -> tuple[Producer, BaseModel]:
    """认产出者 → 问它能不能挂在这种格子上 → 校验表单。跑和干跑的前半截是同一段。"""
    producer = get_producer(db, request.producer, request.actor_id)
    if request.kind not in producer.hosts:
        raise BoardInputError("boardErr_producerCannotHost", producer=producer.id, kind=request.kind)
    try:
        form = producer.form.model_validate(request.form)
    except ValidationError as exc:
        raise ProducerFormInvalid(producer.id, exc.errors(include_url=False, include_context=False)) from exc
    return producer, form


def _failed(producer: Producer, exc: Exception) -> ProducerFailed:
    failed = ProducerFailed.relay(exc)
    failed.status = producer.failure_status
    return failed


def run(db: Session, request: RunRequest) -> Board:
    """跑一次产出者。**画板上所有产出都从这里进**:路由、智能体(run_board_item)。

    顺序:认产出者 → 问它能不能挂在这种格子上 → 校验表单 → 起。产出者自己那一侧的错误转成
    ProducerFailed(带着原来的 key 和参数);画板自己的错误(版本冲突、这一格在跑)原样抛。
    """
    producer, form = _admit(db, request)
    try:
        return producer.start(db, request, form)
    except producer.failures as exc:
        raise _failed(producer, exc) from exc


def dry_run(db: Session, request: RunRequest) -> tuple[Producer, dict[str, Any]]:
    """把 run 在建任务之前会问的全问一遍,**不建任务、不动画布**。返回产出者和它给出的事实。

    给「替人点运行之前先开一张卡」用(智能体的 run_board_item):注定起不了任务的卡(没有连接、
    这一格在跑、数字字段填错了)在开卡时就拒;卡上说的连接,就是待会儿真跑时解析出来的那一条。
    """
    producer, form = _admit(db, request)
    if producer.preflight is None:
        return producer, {}
    try:
        return producer, producer.preflight(db, request, form)
    except producer.failures as exc:
        raise _failed(producer, exc) from exc


def check_forms(db: Session, canvas: dict[str, Any], item_ids: list[str], actor_id: str | None) -> None:
    """替人写下的表单(智能体 edit_board 放的、改的工具格)在这张画布上说得通,说不通抛 BoardDomainError。

    `canvas` 是算子作用之后、**落库之前**的那一份(形状已经由 normalize 过了一遍)—— 绑定要在
    normalize 摘掉断线的那几条**之前**看:写一条没连线的绑定是一个正在写的错,落库时悄悄摘掉的话,
    智能体以为接上了,用户点运行时那个字段是空的。

    问的和界面同一张注册表、同一张「什么能接什么」(tools.check_bindings):

    · 这个人有这个产出者(插件工具是他自己接的连接暴露的 —— 没有的话说清楚是哪个插件);
    · 它能挂在这种格子上;
    · 工具的表单:配置里只有这个工具声明过的字段,声明成数字的是数,绑定都接得上。

    内置产出者(写字、生成、念、截)的表单是各自面板的形状,归面板,这里只问前两样。
    """
    from app.domain.boards.tools import check_bindings
    from app.domain.boards.transforms import wiring_field
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.binding import check_number_fields

    registry = _registry(db, actor_id)
    by_id = {str(one.get("id")): one for one in canvas.get("items") or []}
    for item_id in item_ids:
        item = by_id[item_id]
        form = dict(item.get("form") or {})
        producer_id = str(form.get("producer") or "")
        if not producer_id:
            continue
        producer = registry.get(producer_id) or get_producer(db, producer_id, actor_id)
        if item.get("kind") not in producer.hosts:
            raise BoardInputError("boardErr_producerCannotHost", producer=producer.id, kind=str(item.get("kind")))
        node_type = node_type_of(producer.id)
        if node_type is None:
            continue
        config = form.get("config") or {}
        try:
            node_form = NodeForm.model_validate({"config": config, "bindings": form.get("bindings") or {}})
        except ValidationError as exc:
            raise ProducerFormInvalid(producer.id, exc.errors(include_url=False, include_context=False)) from exc
        #: 画板上露出来的那几个字段(boards.transforms.wiring_field):映射、原始 JSON、代码这类字段
        #: 在画板的表单上根本不出现,替人写进去等于留一份面板打开也看不见、改不了的配置。
        specs = {key: spec for key, spec in ((producer.meta or {}).get("config") or {}).items()
                 if not wiring_field(key, spec)}
        for key in config:
            if key not in specs:
                raise BoardInputError("boardErr_toolConfigUnknownField", tool=producer.id, field=key,
                                      fields=", ".join(specs) or "-")
        try:
            check_number_fields(node_type, dict(config))
        except WorkflowDomainError as exc:
            raise BoardInputError.relay(exc) from exc
        check_bindings(canvas, item_id, specs,
                       {field: [{"from": ref.source} for ref in refs] for field, refs in node_form.bindings.items()},
                       tool=producer.id)
