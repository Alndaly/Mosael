"""画板上的产出者(Producer)注册表 —— 画板上「能产出东西的动作」只有这一个入口(ADR 0021)。

此前是写死的四条路:生成、念、截、写,各有一个路由、一个请求体、一块面板,挂哪块面板由前端按
item 种类猜。第五种产出(插件工具、挑过的工作流节点)想上画板,就得再开第五条路由、第五块面板。
现在四个动作是注册表里的四个内置产出者,一次运行的形状只有一个(RunRequest),路由只有一条
(`POST /api/boards/{id}/run`),面板由表单上写明的 `form.producer` 决定。

第五种产出 —— 跑一个工作流节点(插件工具、声明了能上画板的内置节点)—— 是 `node:<节点类型>`;
它们不在这里逐个登记,而是从节点注册表里读(见 _node_producers)。**画板上没有单独的工具格**:
一个节点要么是内容格的一项**能力**(音频格转写、便签翻译,宿主的内容就是它的输入,产出新建在右边),
要么是空格子的一种**填法**(按参数出图出片的生成器,和「配音 / 生成」同一个切换)—— 由它自己的声明推
(boards.transforms 的 board_role / board_hosts,ADR 0025 修订「能力住在内容格上」)。

一个产出者说清六件事:

· `hosts` —— 能挂在哪些 item 种类上(画板项的 kind);
· `role` —— `slot`(这一格自己的产出者,写在 `form.producer`)还是 `ability`(内容格的一项能力,
  设置存在 `form.abilities[产出者]`,跑的时候宿主的内容就是输入);
· `permission` —— 跑它要的工作区权限(ensure_workspace_perm 的操作名);
· `effects` —— 有没有花钱或对外的副作用(智能体替人跑时要不要确认卡,见 ADR 0021 决定 2);
· `form` —— 它收的表单(pydantic)。**表单在领域里校验**:第二个入口(智能体、工作流)
  跑同一个产出者时,拿到的是同一份校验,不必各自再写一遍;
· `start` —— 建任务 → 摆占位 → 起任务,返回摆好占位的画板。

跑之前的检查(dry_run)和替人写下的表单的检查(check_forms)也在这里 —— 智能体替人写能力的设置、
替人点运行,问的是和界面**同一张注册表**,不另写一份「什么能跑、什么能接」。

内置的本体仍在 `actions`(`*_on_board`),这里只把它们登记成同一种东西。3D 场景格上的渲白模
(`scene_render`)是个例外:它跑的就是工作流那个节点的执行器(boards.tools.run_node_on_board),只是挂在
场景格上、场景由那一格给 —— 和能力同一条运行的路,产出同样新建成右边的几格。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

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
from app.domain.boards.producer_ids import (
    BUILTIN_PRODUCER_IDS,
    SCENE_PRODUCER,
    node_producer_id,
    node_type_of,
    runs_from_draft,
)
from app.domain.boards.transforms import ABILITY, SLOT


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
    #: 节点产出者就是那个节点自己的条目;内置的只有名字和一句说明(它们的面板是专门写的)。
    meta: dict[str, Any] | None = None
    #: 能不能挑来填一个**空槽**(hosts 里那几种格子刚放下、还没有产出时)。一种格子有两个这样的
    #: 产出者时(音频槽:念一段 / 生成音乐音效 / 插件的生成器),面板上给一个切换。截一段不是 —— 它得先有一段素材。
    fills_empty_slot: bool = False
    #: `slot`:这一格自己的产出者(`form.producer`);`ability`:内容格的一项能力(见模块开头)。
    role: str = SLOT
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
    #: 落在这一格上、用户可再次编辑的表单(草稿)。**和上面几样不是同一份**,所以不能由它们推出来:
    #: 上面的 `prompt` 是发出去的那句(带着运行时追加的图例、拼进来的文档正文),`source_assets` 是
    #: 槽位挂的并上正文里 @ 到的;这里存的是用户写的那句、`prompt_document`、`mentioned_asset_ids`,
    #: 槽位只是槽位那一半 —— 重试时照它还原面板,@ 删掉的素材才不会被当成槽位里的再发一次。
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


#: 渲白模在场景格上收的那几个字段 —— **就是工作流节点 `scene_render` 声明的那几个**(字段说明、选项来源、
#: 「只有一个镜头就用它」都读那一份,见 _scene_render_meta),少了 `scene_id`:场景由宿主那一格给。
SCENE_RENDER_FIELDS = ("shot_id", "render", "project_id")


class SceneRenderConfig(_Form):
    """场景格上渲白模的设置。和节点的配置同名同义;画板上没有 `{{…}}`,所以「渲什么」只收那三种。"""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    #: 留空 = 场景只有一个镜头时用它(和节点同一条规矩,见 scenes.render_shot_references)。
    shot_id: str = Field(default="", max_length=128)
    #: 取值和节点的选项是同一张表(scenes.REFERENCE_RENDERS),棘轮钉着。
    render: Literal["stills", "video", "both"] = "stills"
    #: 渲出来的素材归档进哪个项目;留空不归档。
    project_id: str = Field(default="", max_length=64)


class SceneRenderForm(_Form):
    """场景格上的表单。**存在那一格上的就是这一份**(`form.config`),和能力的设置一样:跑完不清,下一次照它再渲 ——
    智能体替人点运行时读的也是它。"""

    config: SceneRenderConfig = Field(default_factory=SceneRenderConfig)


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


#: 渲白模吃的是宿主那一格的场景:节点的 `scene_id` 字段,接的是 3D 场景(和能力吃宿主内容同一条,
#: boards.tools.prepare_node_run 的 host_input)。
_SCENE_HOST = ("scene_id", "scene")


def _scene_render_args(form: SceneRenderForm) -> dict[str, Any]:
    """场景格上的一次渲染 → 跑节点那条路要的东西:节点配置(空着的字段不写,节点照自己的缺省)、宿主给的场景。

    `meta` 是渲白模自己那一份(_scene_render_meta):落板的输出按它点名的三份素材算,不是节点的全部输出。
    """
    return {
        "node_type": SCENE_PRODUCER,
        "meta": _scene_render_meta(),
        "config": {key: value for key, value in form.config.model_dump().items() if value != ""},
        "bindings": {},
        "host_input": _SCENE_HOST,
    }


def _start_scene_render(db: Session, request: RunRequest, form: SceneRenderForm) -> Board:
    """在场景格上渲一次:**工作流节点 `scene_render` 的同一个执行器**,走能力那条路(建 `board_run` 任务、
    挂在它下面计量、能停),产出新建成场景格右边的几格(canvas._derive)。场景格自己不动。"""
    from app.core.i18n import get_current_locale, t
    from app.domain.boards.tools import run_node_on_board

    return run_node_on_board(
        db,
        request=request,
        **_scene_render_args(form),
        label=t("boardProducer_scene_render", get_current_locale()),
        draft={"config": form.config.model_dump(exclude_unset=True)},
    )


def _preflight_scene_render(db: Session, request: RunRequest, form: SceneRenderForm) -> dict[str, Any]:
    from app.core.i18n import get_current_locale, t
    from app.domain.boards.tools import prepare_node_run

    prepare_node_run(db, request=request, **_scene_render_args(form),
                     label=t("boardProducer_scene_render", get_current_locale()))
    return {}


def _scene_render_meta() -> dict[str, Any]:
    """渲白模给界面的描述:名字和一句说明是画板自己的,**字段和输出是工作流节点那一份**(不抄)——
    字段说明、选项来源(场景的镜头、工作区的项目)、「只有一个镜头就用它」、每个输出是哪种素材。

    落板的只有三份素材(首帧、尾帧、运镜视频);镜头语言、跳过的模型、模型提醒是给工作流连线的。
    """
    from app.domain.workflows import NODE_TYPES

    node = NODE_TYPES[SCENE_PRODUCER]
    config = {key: dict(node["config"][key]) for key in SCENE_RENDER_FIELDS}
    #: 画板上没有 `{{…}}`:渲什么只在那三种里挑(节点允许手填,是给整片流程逐镜传值用的)。
    config["render"].pop("allow_custom", None)
    return {
        **_builtin_meta(SCENE_PRODUCER),
        "config": config,
        "outputs": list(node["outputs"]),
        "output_types": dict(node.get("output_types") or {}),
        "output_labels": dict(node.get("output_labels") or {}),
        "output_media": dict(node.get("output_media") or {}),
        "board_outputs": ["first_frame_asset_id", "last_frame_asset_id", "video_asset_id"],
    }


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
    """内置产出者。**导入期不碰这些领域** —— 生成、配音、截取各自的模块很重,且会回头
    认识画板;错误类型在这里才取。"""
    from app.domain.ai_chat import AiChatError
    from app.domain.boards.trim import TrimError
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.resolution import KINDS as GENERATION_KINDS
    from app.domain.voices.voices import VoiceError
    from app.domain.workflows import WorkflowDomainError

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
            Producer(
                id=SCENE_PRODUCER,
                meta=_scene_render_meta(),
                #: 场景格永远「还能再渲」:它的内容是场景本身,渲出来的落在右边(producer_ids.DERIVED_BUILTINS)。
                #: 新放下的场景格挂的就是它(SLOT_PRODUCERS)。
                fills_empty_slot=True,
                hosts=("scene",),
                permission="edit",
                #: 本机渲染,不花钱、不出门 —— 智能体替人跑不用开卡。
                effects="none",
                form=SceneRenderForm,
                start=_start_scene_render,
                preflight=_preflight_scene_render,
                #: 起任务之前就会失败的那几种(和能力同一条路,见 boards.tools.prepare_node_run)。
                failures=(WorkflowDomainError,),
            ),
        )
    }


def list_producers(db: Session, actor_id: str | None) -> list[Producer]:
    """`actor_id` 这个人在画板上能用的全部产出者:内置的,加上画板上能跑的节点(见 _node_producers)。

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
    """一个节点产出者此刻跑不了:说清是哪一种情况。总是抛。"""
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
                #: 空格子上存着的这种生成器会被对账改写成生成,还没改到的这一格在这里说清楚)。
                raise BoardInputError("boardErr_toolMirroredByGeneration", tool=str(tool.get("label") or tool_name),
                                      model=str(row.display_name or row.model_id))
        #: 他接着这个插件、工具也开着,只是它不是一个内容变换(列清单、看状态、上传、按编号取回……)——
        #: 这不是「去插件页建连接」能解决的事,是「这件事在工作流里做」。清单会变(ComfyUI 的工具随
        #: 服务器上的工作流),所以画布上存着一个此刻不合格的产出者是正常的,跑的时候说清楚:叫得出工具的名字,
        #: 按编号取东西的说它是在按编号取东西(它明明交出素材,「它不交出素材」那句是错的)。
        label = str(mine_exposed[0].get("label") or tool_name)
        if content_transform_gap(node_meta(mine_exposed[0])) == "external_id":
            raise BoardInputError("boardErr_toolFetchesByExternalId", tool=label)
        raise BoardInputError("boardErr_toolNotOnBoard", tool=label)
    raise BoardInputError("boardErr_pluginNotConnected", plugin=package.name if package is not None else package_id,
                          tool=tool_name)


class BindingRef(_Form):
    """绑定的一条:这个字段的值从上游哪一格来。"""

    model_config = ConfigDict(allow_inf_nan=False, populate_by_name=True)

    source: str = Field(alias="from", min_length=1, max_length=128)


class NodeForm(_Form):
    """节点产出者的表单(一项能力存在宿主上的设置、空格子上生成器的表单):节点配置(键是节点声明的字段)
    + 哪些字段接上游。

    配置的逐字段校验归节点自己(执行器、check_number_fields)—— 插件节点的字段是运行时才知道的,
    在这里写一份 pydantic 等于第二份声明。
    """

    config: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, list[BindingRef]] = Field(default_factory=dict)


def _node_producers(db: Session, actor_id: str | None) -> dict[str, Producer]:
    """画板上能跑的节点。两个来源,**都从节点注册表里读**,画板这边不列清单;两个来源过**同一条**
    规矩 —— 画板上只放内容变换(boards.transforms.is_content_transform,ADR 0021 修订)。挂在哪、是能力还是
    填法也从声明推(boards.transforms.board_role / board_hosts):

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
    from app.domain.boards.transforms import board_hosts, board_role, host_field, host_sink
    from app.domain.notes import NoteDomainError
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.workflows import WorkflowDomainError

    role = board_role(meta)

    def bindings_of(form: NodeForm) -> dict[str, list[dict[str, str]]]:
        return {field: [{"from": ref.source} for ref in refs] for field, refs in form.bindings.items()}

    def host_input(kind: str) -> tuple[str, str] | None:
        """能力挂在 `kind` 这种格子上时,宿主的内容填进哪个字段、接的是什么。填法没有(它不吃内容)。"""
        field = host_field(meta, kind) if role == ABILITY else None
        return (field, str(host_sink(meta, field))) if field else None

    def label() -> str:
        from app.core.i18n import get_current_locale, t

        #: 任务中心里这一条叫什么(节点的名字);宿主还没有内容时的那句话也叫它。
        return t(str(meta.get("label") or node_type), get_current_locale())

    def start(db: Session, request: RunRequest, form: NodeForm) -> Board:
        from app.domain.boards.tools import run_node_on_board

        return run_node_on_board(
            db,
            request=request,
            node_type=node_type,
            meta=meta,
            config=dict(form.config),
            bindings=bindings_of(form),
            label=label(),
            host_input=host_input(request.kind),
            ability=role == ABILITY,
        )

    def preflight(db: Session, request: RunRequest, form: NodeForm) -> dict[str, Any]:
        from app.db.models import PluginInstance
        from app.domain.boards.tools import prepare_node_run
        from app.domain.plugins.nodes import parse_node_type

        _board, resolved = prepare_node_run(db, request=request, node_type=node_type, meta=meta,
                                            config=dict(form.config), bindings=bindings_of(form),
                                            host_input=host_input(request.kind), label=label())
        #: 插件工具用的是**这个人**自己的哪条连接(prepare 已经按人解析好了)。
        plugin = parse_node_type(node_type) is not None
        instance = db.get(PluginInstance, str(resolved.get("instance_id") or "")) if plugin else None
        return {"connection": instance.name if instance is not None else ""}

    return Producer(
        id=node_producer_id(node_type),
        hosts=board_hosts(meta),
        role=role,
        #: 填法就是空格子的一种填法:和「配音 / 生成」一起出现在那种格子的切换里。
        fills_empty_slot=role == SLOT,
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
    挂在哪(hosts)、是这一格自己的产出者还是它的一项能力(role)、要什么权限、有没有外部后果、
    能不能挑来填一个空槽。

    每个配置字段多一样 `board_sources`:它能接哪几种上游格子(见 boards.tools.bindable_kinds)。
    面板照它列绑定,不在前端另写一套「什么能接什么」。能力还多一样 `host_fields`({宿主种类: 字段}):
    宿主的内容填进哪个字段 —— 那个字段在面板上不出现,它**就是**宿主。

    节点产出者(`node:*`)的描述是**画板的那一份**,不照搬工作流的(boards.transforms):字段只留创作者
    看得懂的(映射、原始 JSON、代码不出现,模板字段是一段字);`board_group` / `board_group_label` 说
    它按吃什么内容归哪一组(能力图标的兜底),`board_description` 是给创作者看的一句说明。
    顺序就是注册表的顺序:内置的、内置节点、插件工具 —— 操作条上能力按它排,内置的在前。
    """
    from app.core.i18n import t
    from app.domain.boards.tools import bindable_kinds
    from app.domain.boards.transforms import (
        board_config_view,
        board_description,
        board_group,
        host_fields,
        output_kinds,
    )
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
    out = []
    for producer_id, producer in registry.items():
        entry = dict(by_id[producer_id])
        node_type = node_type_of(producer_id)
        board: dict[str, Any] = {}
        if node_type is not None:
            group = board_group(producer.meta or {})
            board = {
                "config": board_config_view(entry["config"]),
                "board_group": group,
                "board_group_label": t(f"boardToolGroup_{group}", locale),
                "board_description": board_description(producer.meta or {}, locale),
                "output_kinds": output_kinds(producer.meta or {}),
                "host_fields": host_fields(producer.meta or {}),
            }
        elif runs_from_draft(producer_id):
            #: 表单是节点字段的内置产出者(3D 场景格渲白模):字段照节点那一份画板视图发,面板照它长。
            board = {
                "config": board_config_view(entry["config"]),
                "board_description": board_description(producer.meta or {}, locale),
                "output_kinds": output_kinds(producer.meta or {}),
            }
        out.append({
            **entry,
            **board,
            #: `type` 是节点类型(字段选项接口认的是它);`id` 是产出者的名字(存在表单上、跑的时候发的是它)。
            "type": node_type or producer_id,
            "id": producer_id,
            "hosts": list(producer.hosts),
            "role": producer.role,
            "permission": producer.permission,
            "effects": producer.effects,
            "fills_empty_slot": producer.fills_empty_slot,
            "runs_from_draft": runs_from_draft(producer_id),
        })
    return out


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


#: 替人写下的一份表单在哪儿:`(格子 id, None)` 是那一格自己的表单,`(格子 id, 产出者)` 是它的那一项能力。
FormRef = tuple[str, str | None]


def written_forms(before: dict[str, Any], after: dict[str, Any]) -> list[FormRef]:
    """两份画布之间**变了的**表单:每一格自己那一份(不算能力)、每一项能力的设置,各算一份。

    只问变了的:一格上存着别的能力的设置,它的插件此刻卸了(或者是别人接的),和这一次写的东西无关 ——
    拿它去拦这一次改动,就是一张打不开的板换了个样子。
    """
    was = {str(one.get("id")): dict(one.get("form") or {}) for one in before.get("items") or []}
    out: list[FormRef] = []
    for item in after.get("items") or []:
        item_id = str(item.get("id"))
        form = dict(item.get("form") or {})
        old = was.get(item_id, {})
        abilities = form.pop("abilities", None) or {}
        old_abilities = old.pop("abilities", None) or {}
        if form != old:
            out.append((item_id, None))
        out.extend((item_id, producer) for producer, entry in abilities.items() if entry != old_abilities.get(producer))
    return out


def check_forms(db: Session, canvas: dict[str, Any], written: list[FormRef], actor_id: str | None) -> None:
    """替人写下的表单(智能体 edit_board 放的、改的)在这张画布上说得通,说不通抛 BoardDomainError。

    `canvas` 是算子作用之后、**落库之前**的那一份(形状已经由 normalize 过了一遍)—— 绑定要在
    normalize 摘掉断线的那几条**之前**看:写一条没连线的绑定是一个正在写的错,落库时悄悄摘掉的话,
    智能体以为接上了,用户点运行时那个字段是空的。`written` 是这一次写了的那几份(见 written_forms)。

    问的和界面同一张注册表、同一张「什么能接什么」(tools.check_bindings):

    · 这个人有这个产出者(插件工具是他自己接的连接暴露的 —— 没有的话说清楚是哪个插件);
    · 它能挂在这种格子上,角色对得上:一格自己的产出者得是这种格子的填法(`slot`),写进 `abilities` 的得是它的
      一项能力(`ability`);
    · 节点的表单:配置里只有画板上露出来的字段(能力的话,宿主填的那个字段也不算 —— 它就是宿主),声明成数字的
      是数,绑定都接得上。

    内置产出者(写字、生成、念、截)的表单是各自面板的形状,归面板,这里只问前两样;3D 场景格上渲白模的表单
    存的就是运行发的那一份(runs_from_draft),照它自己的表单模型校验。
    """
    registry = _registry(db, actor_id)
    by_id = {str(one.get("id")): one for one in canvas.get("items") or []}
    for item_id, ability in written:
        item = by_id[item_id]
        kind = str(item.get("kind"))
        form = dict(item.get("form") or {})
        if ability is not None:
            producer = registry.get(ability) or get_producer(db, ability, actor_id)
            if producer.role != ABILITY or kind not in producer.hosts:
                raise BoardInputError("boardErr_abilityNotOnKind", producer=producer.id, kind=kind,
                                      kinds=", ".join(producer.hosts) or "-")
            entry = dict((form.get("abilities") or {}).get(ability) or {})
            _check_node_form(canvas, item_id, producer, entry, kind)
            continue
        producer_id = str(form.get("producer") or "")
        if not producer_id:
            continue
        producer = registry.get(producer_id) or get_producer(db, producer_id, actor_id)
        if kind not in producer.hosts:
            raise BoardInputError("boardErr_producerCannotHost", producer=producer.id, kind=kind)
        if producer.role == ABILITY:
            raise BoardInputError("boardErr_abilityIsNotAProducer", producer=producer.id, kind=kind, item_id=item_id)
        if node_type_of(producer.id) is not None:
            _check_node_form(canvas, item_id, producer, form, kind)
        elif runs_from_draft(producer.id):
            try:
                producer.form.model_validate({key: value for key, value in form.items()
                                              if key not in ("producer", "abilities")})
            except ValidationError as exc:
                raise ProducerFormInvalid(producer.id, exc.errors(include_url=False, include_context=False)) from exc


def _check_node_form(canvas: dict[str, Any], item_id: str, producer: Producer, form: dict[str, Any], kind: str) -> None:
    """一份节点产出者的表单(`{config, bindings}`)在这一格上说得通。"""
    from app.domain.boards.tools import check_bindings
    from app.domain.boards.transforms import external_id_field, host_field, wiring_field
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.binding import check_number_fields

    config = form.get("config") or {}
    try:
        node_form = NodeForm.model_validate({"config": config, "bindings": form.get("bindings") or {}})
    except ValidationError as exc:
        raise ProducerFormInvalid(producer.id, exc.errors(include_url=False, include_context=False)) from exc
    #: 画板上露出来的那几个字段(boards.transforms.board_config_view):映射、原始 JSON、代码、另一个系统里的编号
    #: 在画板的表单上根本不出现,替人写进去等于留一份面板打开也看不见、改不了的配置。能力的宿主字段也不在:
    #: 那个值就是宿主这一格的内容。
    meta = producer.meta or {}
    host = host_field(meta, kind) if producer.role == ABILITY else None
    specs = {key: spec for key, spec in (meta.get("config") or {}).items()
             if not wiring_field(key, spec) and not external_id_field(key, spec) and key != host}
    for key in config:
        if key not in specs:
            raise BoardInputError("boardErr_toolConfigUnknownField", tool=producer.id, field=key,
                                  fields=", ".join(specs) or "-")
    try:
        check_number_fields(str(node_type_of(producer.id)), dict(config))
    except WorkflowDomainError as exc:
        raise BoardInputError.relay(exc) from exc
    check_bindings(canvas, item_id, specs,
                   {field: [{"from": ref.source} for ref in refs] for field, refs in node_form.bindings.items()},
                   tool=producer.id)
