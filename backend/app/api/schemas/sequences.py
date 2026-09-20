"""时间线:序列、轨、片段,以及编辑器发来的每一种编辑请求。

请求体多是因为**每一种编辑都是一个具名算子**(见 domain/sequences/operations):
它们要能被记录、被撤销、被智能体调用,所以不合并成一个万能的 patch。"""

from __future__ import annotations

from typing import Literal
from pydantic import Field, field_validator
from app.api.schemas.base import ApiModel, OrmModel

class SequenceCreate(ApiModel):
    workspace_id: str
    project_id: str
    name: str = Field(min_length=1, max_length=180)
    width: int = 1920
    height: int = 1080
    fps: float = 30.0


class ClipOut(OrmModel):
    id: str
    workspace_id: str
    sequence_id: str
    track_id: str
    asset_id: str | None
    #: 这一段用的是哪一类素材(video/audio/image/…)。**轨道类型说明不了它** —— 视频轨上完全
    #: 可以放图片(AI 生成的静图就是这么落上去的),而界面要据此判断"这一段能不能转写"。
    asset_kind: str = ""
    timeline_start: float
    src_in: float
    src_out: float
    speed: float
    gain: float
    muted: bool
    linked_clip_id: str | None
    text_override: str | None
    effects: dict
    transform: dict = Field(default_factory=dict)

    @field_validator("transform", "effects", mode="before")
    @classmethod
    def _none_to_dict(cls, value: object) -> object:
        return {} if value is None else value


class TrackOut(OrmModel):
    id: str
    sequence_id: str
    kind: str
    name: str
    position: int
    locked: bool
    muted: bool
    solo: bool = False
    duck: bool = False
    #: 这条轨的用途;空 = 普通轨。界面据此认出「配音轨」并把再一次的配音放回同一条。
    role: str = ""
    clips: list[ClipOut] = Field(default_factory=list)


class SetSequenceReframeRequest(ApiModel):
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=8192)
    fill_mode: str = Field(default="cover", pattern="^(cover|contain|blur)$")


class SequenceOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str
    name: str
    width: int
    height: int
    fps: float
    reframe: dict = Field(default_factory=dict)
    subtitle_style: dict = Field(default_factory=dict)
    revision: int

    @field_validator("reframe", "subtitle_style", mode="before")
    @classmethod
    def _none_to_dict(cls, value: object) -> object:
        return {} if value is None else value
    can_undo: bool = False
    can_redo: bool = False
    tracks: list[TrackOut] = Field(default_factory=list)


class InsertClipRequest(ApiModel):
    track_id: str
    asset_id: str
    timeline_start: float = 0.0
    src_in: float = 0.0
    src_out: float
    ripple: bool = False


class MoveClipRequest(ApiModel):
    timeline_start: float
    track_id: str | None = None
    ripple: bool = False


class ClipMoveEntry(ApiModel):
    clip_id: str
    timeline_start: float
    track_id: str | None = None


class ClipIdsRequest(ApiModel):
    """多选批量操作的通用入参:一次手势一条操作,撤销一步全部还原。"""

    clip_ids: list[str] = Field(min_length=1)


class MoveClipsBatchRequest(ApiModel):
    """框选后整组拖动。没有 ripple —— 一组片段要"挤开"什么没有唯一解,组拖按覆盖语义。"""

    moves: list[ClipMoveEntry] = Field(min_length=1)


class TrimClipRequest(ApiModel):
    timeline_start: float
    src_in: float
    src_out: float


class ExportRequest(ApiModel):
    """导出参数;整个 body 可省略(老调用方/工作流节点按默认档导出)。"""

    resolution: Literal["original", "1080p", "720p", "480p"] = "original"
    fps: float | None = Field(default=None, ge=1, le=120)
    quality: Literal["high", "standard", "compact"] = "standard"


class CutClipRangeRequest(ApiModel):
    src_start: float
    src_end: float


class CutClipRangesRequest(ApiModel):
    ranges: list[CutClipRangeRequest] = Field(min_length=1)


class ClipRangeCutsRequest(ApiModel):
    clip_id: str
    ranges: list[CutClipRangeRequest] = Field(min_length=1)


class CutClipRangesBatchRequest(ApiModel):
    """一次字幕裁切手势涉及的全部片段。整批只产生一条时间线操作。"""

    cuts: list[ClipRangeCutsRequest] = Field(min_length=1)


class SplitClipRequest(ApiModel):
    src_time: float


class SplitClipPointsRequest(ApiModel):
    src_times: list[float] = Field(min_length=1)


class ClipPointSplitsRequest(ApiModel):
    clip_id: str
    src_times: list[float] = Field(min_length=1)


class SplitClipPointsBatchRequest(ApiModel):
    """一次字幕切分手势涉及的全部片段。整批只产生一条时间线操作。"""

    splits: list[ClipPointSplitsRequest] = Field(min_length=1)


class MoveTrackRequest(ApiModel):
    direction: str = Field(pattern="^(up|down)$")


class SubtitleCueInput(ApiModel):
    text: str
    timeline_start: float
    duration: float


class GenerateSubtitlesRequest(ApiModel):
    track_id: str
    cues: list[SubtitleCueInput] = Field(min_length=1)


class SetSubtitleStyleRequest(ApiModel):
    style: dict


class SetTrackStateRequest(ApiModel):
    muted: bool | None = None
    locked: bool | None = None
    solo: bool | None = None
    duck: bool | None = None


class AddTrackRequest(ApiModel):
    kind: str = Field(pattern="^(video|audio|subtitle)$")


class SetClipEffectsRequest(ApiModel):
    effects: dict = Field(default_factory=dict)


class SetClipSpeedRequest(ApiModel):
    speed: float = Field(ge=0.25, le=4.0)


class SetClipGainRequest(ApiModel):
    gain: float = Field(ge=0.0, le=4.0)
    muted: bool = False


class TranslateRequest(ApiModel):
    #: 这次翻译算在哪个工作区头上。以前没有这个字段 —— 于是这个接口回答不了「这笔钱算谁的」,
    #: 而用量表的 workspace_id 是 NOT NULL,AI 翻译因此一条账都记不了。补的是建模缺失,
    #: 不是一道闸门:它同时把这个接口纳入了工作区权限体系。
    workspace_id: str
    #: 一次请求的条数上限。这是**防止一次请求打垮自己**的安全阀,不是「能翻多少字幕」的答案 ——
    #: 一条一小时视频的字幕轨轻松上千条。分批在客户端做(见 frontend/src/api/client.translateTexts,
    #: 那是唯一出口),所以这里不必为了迁就轨道长度把它调大:每一批都在这个数以内。
    texts: list[str] = Field(min_length=1, max_length=500)
    target_lang: str
    engine: str = Field(default="google", pattern="^(google|ai)$")
    profile_id: str | None = None


class TranslateResponse(ApiModel):
    translations: list[str]


class SetClipTransformRequest(ApiModel):
    transform: dict = Field(default_factory=dict)  # {scale,x,y,rotation,opacity};后端按范围钳制


class InsertTextClipRequest(ApiModel):
    track_id: str
    text: str = Field(min_length=1, max_length=500)
    timeline_start: float = 0.0
    duration: float = Field(default=2.0, gt=0)


class SetClipTextRequest(ApiModel):
    text: str = Field(min_length=1, max_length=500)


class ClipTextEntry(ApiModel):
    clip_id: str
    text: str = Field(min_length=1, max_length=500)


class SetClipTextsRequest(ApiModel):
    # Bounded so one request cannot rewrite an unbounded number of clips in a single revision.
    texts: list[ClipTextEntry] = Field(min_length=1, max_length=2000)
