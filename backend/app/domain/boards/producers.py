"""画板上的产出者(Producer)注册表 —— 画板上「能产出东西的动作」只有这一个入口(ADR 0021)。

此前是写死的四条路:生成、念、截、写,各有一个路由、一个请求体、一块面板,挂哪块面板由前端按
item 种类猜。第五种产出(插件工具、挑过的工作流节点)想上画板,就得再开第五条路由、第五块面板。
现在四个动作是注册表里的四个内置产出者,一次运行的形状只有一个(RunRequest),路由只有一条
(`POST /api/boards/{id}/run`),面板由表单上写明的 `form.producer` 决定。

一个产出者说清五件事:

· `hosts` —— 能挂在哪些 item 种类上(画板项的 kind);
· `permission` —— 跑它要的工作区权限(ensure_workspace_perm 的操作名);
· `effects` —— 有没有花钱或对外的副作用(智能体替人跑时要不要确认卡,见 ADR 0021 决定 2);
· `form` —— 它收的表单(pydantic)。**表单在领域里校验**:第二个入口(智能体、工作流)
  跑同一个产出者时,拿到的是同一份校验,不必各自再写一遍;
· `start` —— 建任务 → 摆占位 → 起任务,返回摆好占位的画板。

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
    #: "none" | "paid" | "external" —— 智能体替人跑时,不是 none 的要确认卡(ADR 0021 决定 2)。
    effects: str
    form: type[BaseModel]
    start: Callable[[Session, RunRequest, Any], Board]
    #: 产出者那一侧会抛的领域错误,以及它们翻成的状态码(见 ProducerFailed)。
    failures: tuple[type[Exception], ...] = ()
    failure_status: int = 400


class _Form(BaseModel):
    """产出者表单的基类。和接口层的 ApiModel 同一条规矩:**不收 NaN / Infinity**。"""

    model_config = ConfigDict(allow_inf_nan=False)


class SourceRef(_Form):
    """生成时挂进槽位的一份素材及其用途。角色取值由生成契约给(见 contracts.generation)。"""

    asset_id: str = Field(min_length=1, max_length=64)
    role: str = Field(default=FIRST_FRAME, pattern=f"^({'|'.join(SOURCE_ROLES)})$")


class GenerateForm(_Form):
    #: 发给模型的那句提示词(可带运行时追加的图例)。
    prompt: str
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


def list_producers() -> list[Producer]:
    """画板上能用的全部产出者。每次现取 —— 四条登记很便宜,不值得多一份进程内状态。"""
    return list(_builtins().values())


def get_producer(producer_id: str) -> Producer:
    """按 id 取产出者;没有就说清楚有哪些。"""
    registry = _builtins()
    producer = registry.get(str(producer_id or "").strip())
    if producer is None:
        raise BoardInputError("boardErr_unknownProducer", producer=producer_id, producers=", ".join(registry))
    return producer


def producer_for_new_slot(kind: str) -> str | None:
    """新放下的一格(还没有产出)挂哪个产出者。便签写字、音频念、图片/视频生成;别的种类不产出。

    这是**新建时的缺省**,不是读的时候猜:它写进 `form.producer` 之后就是那一格自己的事实,
    改换产出者(P2 的工具格)也只改那一个字段。和前端 boardItemState.newSlotForm 同一张表。
    """
    if kind == "note":
        return "write"
    if kind == "audio":
        return "speak"
    generate = get_producer("generate")
    return generate.id if kind in generate.hosts else None


def run(db: Session, request: RunRequest) -> Board:
    """跑一次产出者。**画板上所有产出都从这里进**:路由、将来的智能体与工作流入口。

    顺序:认产出者 → 问它能不能挂在这种格子上 → 校验表单 → 起。产出者自己那一侧的错误转成
    ProducerFailed(带着原来的 key 和参数);画板自己的错误(版本冲突、这一格在跑)原样抛。
    """
    producer = get_producer(request.producer)
    if request.kind not in producer.hosts:
        raise BoardInputError("boardErr_producerCannotHost", producer=producer.id, kind=request.kind)
    try:
        form = producer.form.model_validate(request.form)
    except ValidationError as exc:
        raise ProducerFormInvalid(producer.id, exc.errors(include_url=False, include_context=False)) from exc
    try:
        return producer.start(db, request, form)
    except producer.failures as exc:
        failed = ProducerFailed.relay(exc)
        failed.status = producer.failure_status
        raise failed from exc
