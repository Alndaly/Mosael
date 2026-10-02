"""`{kind, ...args}` 形式的时间线操作的入参:每种操作一个 pydantic 模型。

这是智能体的 `edit_timeline`、工作流的时间线节点这类「拿一串 JSON 改时间线」的入口认的那一份。此前它们把字典
原样 `**` 进领域的 dataclass,于是:

- 文档写的参数名和真实的对不上(split_clip 文档写 `at` 实际是 `src_time`,改画幅写 `fit` 实际是 `fill_mode`),
  模型照着文档下单,报的是 Python 的 `unexpected keyword argument`;
- `move_clips_batch` 的 moves 是字典,领域要的是 ClipMove,当场 AttributeError;
- `set_clip_gain` 只给 muted 就缺参数崩;数字给成字符串,比大小时 TypeError;
- 而这些全都要等用户**批准之后**才炸 —— 卡开出来了,批了,失败。

现在每种操作的参数在这里声明一次:多给的名字、缺的必填、不是数的数、NaN / Infinity 当场拒,报错里带着正确写法;
智能体看到的说明(`usage`)也从这里生成,文档和校验不可能再是两份。
"""

from __future__ import annotations

import types
import typing
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.sequences.clip_properties import (
    DetachClipAudio,
    SetClipEffects,
    SetClipGain,
    SetClipSpeed,
    SetClipTransform,
    SetSequenceReframe,
)
from app.domain.sequences.cutting import ClipRangeCuts, CutClipRange, CutClipRangesBatch, SplitClip
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.history import HistoryStep
from app.domain.sequences.placement import (
    ClipMove,
    DeleteClip,
    InsertClip,
    MoveClip,
    MoveClipsBatch,
    RippleDeleteClip,
    TrimClip,
)
from app.domain.sequences.text import GenerateSubtitles, InsertTextClip, SetClipText, SetClipTextsBatch, SetSubtitleStyle
from app.domain.sequences.tracks import AddTrack, RemoveTrack, SetTrackState


class _Args(BaseModel):
    """所有入参的共同约束:不认识的名字算错(写错的参数名不能被静默丢掉),数必须是有限的数。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class OpArgs(_Args):
    #: 说明里跟在签名后面的那半句(可空)。写给模型看,越短越好 —— 工具定义每轮重发。
    note: ClassVar[str] = ""

    def to_request(self, actor_id: str | None) -> Any:  # pragma: no cover — 每个子类都覆盖
        raise NotImplementedError


class _Linked(OpArgs):
    """作用于链接组的操作(见 sequences/links):挪、修剪、切、删、变速默认带上同组的片段(画面和分离出去的音频),
    `linked: false` 只动点名的这一段。这个开关每种都有、意思都一样,说明里不逐条列出 —— 签名上标一个 `*`,
    开头说一次(见 LINKED_MARK)。"""

    linked: bool = True


#: 说明里给「作用于链接组」的操作名后面标的记号;它的意思由工具说明的开头说一次。
LINKED_MARK = "*"


class InsertClipArgs(OpArgs):
    track_id: str
    asset_id: str
    timeline_start: float
    src_out: float
    src_in: float = 0.0
    ripple: bool = False
    speed: float = Field(default=1.0, ge=0.25, le=4.0)

    def to_request(self, actor_id: str | None) -> InsertClip:
        return InsertClip(actor_id=actor_id, **self.model_dump())


class MoveClipArgs(_Linked):
    clip_id: str
    timeline_start: float
    track_id: str | None = None
    ripple: bool = False

    def to_request(self, actor_id: str | None) -> MoveClip:
        return MoveClip(actor_id=actor_id, **self.model_dump())


class _Move(_Args):
    clip_id: str
    timeline_start: float
    track_id: str | None = None


class MoveClipsBatchArgs(_Linked):
    moves: list[_Move] = Field(min_length=1)

    def to_request(self, actor_id: str | None) -> MoveClipsBatch:
        moves = tuple(ClipMove(**move.model_dump()) for move in self.moves)
        return MoveClipsBatch(moves=moves, linked=self.linked, actor_id=actor_id)


class TrimClipArgs(_Linked):
    clip_id: str
    timeline_start: float
    src_in: float
    src_out: float

    def to_request(self, actor_id: str | None) -> TrimClip:
        return TrimClip(actor_id=actor_id, **self.model_dump())


class SplitClipArgs(_Linked):
    clip_id: str
    src_time: float

    def to_request(self, actor_id: str | None) -> SplitClip:
        return SplitClip(actor_id=actor_id, **self.model_dump())


class DeleteClipArgs(_Linked):
    clip_id: str

    def to_request(self, actor_id: str | None) -> DeleteClip:
        return DeleteClip(actor_id=actor_id, **self.model_dump())


class RippleDeleteClipArgs(_Linked):
    note = "closes the gap; all_tracks = every unlocked track"
    clip_id: str
    all_tracks: bool = False

    def to_request(self, actor_id: str | None) -> RippleDeleteClip:
        return RippleDeleteClip(actor_id=actor_id, **self.model_dump())


class CutClipRangeArgs(_Linked):
    note = "rest closes up"
    clip_id: str
    src_start: float
    src_end: float

    def to_request(self, actor_id: str | None) -> CutClipRange:
        return CutClipRange(actor_id=actor_id, **self.model_dump())


class _Range(_Args):
    src_start: float
    src_end: float


class _ClipCuts(_Args):
    clip_id: str
    ranges: list[_Range] = Field(min_length=1)


class CutClipRangesBatchArgs(_Linked):
    note = "one entry per clip"
    cuts: list[_ClipCuts] = Field(min_length=1)

    def to_request(self, actor_id: str | None) -> CutClipRangesBatch:
        cuts = tuple(
            ClipRangeCuts(clip_id=cut.clip_id, ranges=tuple((one.src_start, one.src_end) for one in cut.ranges))
            for cut in self.cuts
        )
        return CutClipRangesBatch(cuts=cuts, linked=self.linked, actor_id=actor_id)


class AddTrackArgs(OpArgs):
    track_kind: Literal["video", "audio", "subtitle"] = "video"

    def to_request(self, actor_id: str | None) -> AddTrack:
        return AddTrack(kind=self.track_kind, actor_id=actor_id)


class RemoveTrackArgs(OpArgs):
    track_id: str
    with_clips: bool = False

    def to_request(self, actor_id: str | None) -> RemoveTrack:
        return RemoveTrack(actor_id=actor_id, **self.model_dump())


class SetTrackStateArgs(OpArgs):
    track_id: str
    muted: bool | None = None
    solo: bool | None = None
    duck: bool | None = None
    locked: bool | None = None
    hidden: bool | None = None

    def to_request(self, actor_id: str | None) -> SetTrackState:
        return SetTrackState(actor_id=actor_id, **self.model_dump())


class DetachClipAudioArgs(OpArgs):
    clip_id: str

    def to_request(self, actor_id: str | None) -> DetachClipAudio:
        return DetachClipAudio(actor_id=actor_id, **self.model_dump())


class SetClipEffectsArgs(OpArgs):
    clip_id: str
    effects: dict[str, Any]

    def to_request(self, actor_id: str | None) -> SetClipEffects:
        return SetClipEffects(actor_id=actor_id, **self.model_dump())


class SetClipTransformArgs(OpArgs):
    note = "scale/x/y/rotation/opacity"
    clip_id: str
    transform: dict[str, Any]

    def to_request(self, actor_id: str | None) -> SetClipTransform:
        return SetClipTransform(actor_id=actor_id, **self.model_dump())


class SetClipSpeedArgs(_Linked):
    note = "0.25–4; ripple: later clips follow"
    clip_id: str
    speed: float = Field(ge=0.25, le=4.0)
    ripple: bool = True

    def to_request(self, actor_id: str | None) -> SetClipSpeed:
        return SetClipSpeed(actor_id=actor_id, **self.model_dump())


class SetClipGainArgs(OpArgs):
    note = "omitted = unchanged"
    clip_id: str
    gain: float | None = Field(default=None, ge=0.0, le=4.0)
    muted: bool | None = None

    def to_request(self, actor_id: str | None) -> SetClipGain:
        return SetClipGain(actor_id=actor_id, **self.model_dump())


class SetSequenceReframeArgs(OpArgs):
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)
    fill_mode: Literal["cover", "contain", "blur"] = "cover"

    def to_request(self, actor_id: str | None) -> SetSequenceReframe:
        return SetSequenceReframe(actor_id=actor_id, **self.model_dump())


class InsertTextClipArgs(OpArgs):
    note = "a subtitle cue"
    track_id: str
    text: str = Field(min_length=1)
    timeline_start: float
    duration: float = Field(gt=0)

    def to_request(self, actor_id: str | None) -> InsertTextClip:
        return InsertTextClip(actor_id=actor_id, **self.model_dump())


class _Cue(_Args):
    text: str = Field(min_length=1)
    timeline_start: float
    duration: float = Field(gt=0)


class GenerateSubtitlesArgs(OpArgs):
    track_id: str
    cues: list[_Cue] = Field(min_length=1)

    def to_request(self, actor_id: str | None) -> GenerateSubtitles:
        cues = tuple((cue.text, cue.timeline_start, cue.duration) for cue in self.cues)
        return GenerateSubtitles(track_id=self.track_id, cues=cues, actor_id=actor_id)


class SetClipTextArgs(OpArgs):
    clip_id: str
    text: str = Field(min_length=1)

    def to_request(self, actor_id: str | None) -> SetClipText:
        return SetClipText(actor_id=actor_id, **self.model_dump())


class _Text(_Args):
    clip_id: str
    text: str = Field(min_length=1)


class SetClipTextsBatchArgs(OpArgs):
    texts: list[_Text] = Field(min_length=1)

    def to_request(self, actor_id: str | None) -> SetClipTextsBatch:
        return SetClipTextsBatch(texts=tuple((one.clip_id, one.text) for one in self.texts), actor_id=actor_id)


class SetSubtitleStyleArgs(OpArgs):
    note = "font_size/color/bg_color/bg_opacity/position"
    style: dict[str, Any]

    def to_request(self, actor_id: str | None) -> SetSubtitleStyle:
        return SetSubtitleStyle(actor_id=actor_id, **self.model_dump())


class HistoryArgs(OpArgs):
    note = "refused if the revision moved"
    expected_revision: int | None = None

    def to_request(self, actor_id: str | None) -> HistoryStep:
        return HistoryStep(expected_revision=self.expected_revision, actor_id=actor_id)


def usage(kind: str, model: type[OpArgs]) -> str:
    """`split_clip*(clip_id, src_time)` —— 从模型的字段生成:可选的带 `?`,枚举写出取值,嵌套的列表写出条目的样子;
    作用于链接组的标 `*`(那个 `linked` 开关不逐条写,见 _Linked)。"""
    linked = issubclass(model, _Linked)
    text = f"{kind}{LINKED_MARK if linked else ''}({_fields(model, skip=('linked',) if linked else ())})"
    return f"{text} — {model.note}" if model.note else text


def _fields(model: type[BaseModel], skip: tuple[str, ...] = ()) -> str:
    parts = []
    for name, field in model.model_fields.items():
        if name in skip:
            continue
        mark = "" if field.is_required() else "?"
        parts.append(f"{name}{mark}{_shape(field.annotation)}")
    return ", ".join(parts)


def _shape(annotation: Any) -> str:
    """字段类型里值得写给模型看的那部分:枚举的取值、嵌套条目的字段。标量就只写名字。"""
    origin = typing.get_origin(annotation)
    args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
    if origin is Literal:
        return ":" + "|".join(str(arg) for arg in typing.get_args(annotation))
    if origin is list and args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return ":[{" + _fields(args[0]) + "}]"
    if origin in (typing.Union, types.UnionType) and len(args) == 1:
        return _shape(args[0])
    return ""


def parse(kind: str, model: type[OpArgs], raw: dict[str, Any]) -> OpArgs:
    """按这种操作的模型认一遍参数;不对就说清哪里不对、正确的写法是什么(拿错的参数名直接下单的往往是模型)。"""
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(_problem(error) for error in exc.errors())
        raise SequenceDomainError("seqErr_badOpArgs", kind=kind, problems=problems, usage=usage(kind, model)) from None


def _problem(error: Any) -> str:
    where = ".".join(str(part) for part in error.get("loc", ())) or "?"
    if error.get("type") == "extra_forbidden":
        return f"unknown argument '{where}'"
    if error.get("type") == "missing":
        return f"missing '{where}'"
    return f"'{where}': {error.get('msg', '')}"
