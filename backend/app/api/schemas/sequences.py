"""时间线:序列、轨、片段,以及编辑器发来的每一种编辑请求。

请求体多是因为**每一种编辑都是一个具名算子**(见 domain/sequences/operations):
它们要能被记录、被撤销、被智能体调用,所以不合并成一个万能的 patch。"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from sqlalchemy import inspect as sqlalchemy_inspect
from app.api.schemas.base import ApiModel, OrmModel
from app.domain.sequences import CANVAS_SIZE_RANGE, FPS_RANGE

class SequenceCreate(ApiModel):
    workspace_id: str
    project_id: str
    name: str = Field(min_length=1, max_length=180)
    #: 范围与领域层同一份(sequences._timeline):宽 -5、帧率 0 的序列此前建得出来,到预览、导出才炸。
    width: int = Field(default=1920, ge=CANVAS_SIZE_RANGE[0], le=CANVAS_SIZE_RANGE[1])
    height: int = Field(default=1080, ge=CANVAS_SIZE_RANGE[0], le=CANVAS_SIZE_RANGE[1])
    fps: float = Field(default=30.0, ge=FPS_RANGE[0], le=FPS_RANGE[1])


class ClipOut(OrmModel):
    id: str
    workspace_id: str
    sequence_id: str
    track_id: str
    asset_id: str | None
    #: 这一段用的是哪一类素材(video/audio/image/…)。**轨道类型说明不了它** —— 视频轨上完全
    #: 可以放图片(AI 生成的静图就是这么落上去的),而界面要据此判断"这一段能不能转写"。
    asset_kind: str = ""
    #: 素材是怎么来的(imported / generated / tts / separated……)。逐字稿据此排除分离出来的派生素材。
    asset_source: str = ""
    timeline_start: float
    src_in: float
    src_out: float
    speed: float
    gain: float
    muted: bool
    text_override: str | None
    #: 素材已被删除时的占位:`{asset_id, name, kind, duration}`;素材还在就是 None。
    #: **不能只看 asset_id 为空**——文字片段的 asset_id 同样为空,而它不是脱机。
    offline_asset: dict | None = None
    #: 链接组:同组的片段默认一起移动、修剪、切分、删除(视频与分离出的音频)。None = 没有链接。
    link_group: str | None = None
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
    #: 只管声音;字幕轨上恒为 False(它没有声音)。
    muted: bool
    #: 只管字幕的显示;目前只有字幕轨会是 True。
    hidden: bool = False
    solo: bool = False
    duck: bool = False
    #: 这条轨的用途;空 = 普通轨。界面据此认出「配音轨」并把再一次的配音放回同一条。
    role: str = ""
    clips: list[ClipOut] = Field(default_factory=list)


class SetSequenceReframeRequest(ApiModel):
    width: int = Field(ge=CANVAS_SIZE_RANGE[0], le=CANVAS_SIZE_RANGE[1])
    height: int = Field(ge=CANVAS_SIZE_RANGE[0], le=CANVAS_SIZE_RANGE[1])
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
    #: 时间线上用到的 AI 生成素材(片段上的「AI」角标、导出对话框的标识开关都看它,见 assets/provenance)。
    ai_asset_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="wrap")
    @classmethod
    def _with_ai_assets(cls, value: Any, handler: Any) -> SequenceOut:
        """从库里的序列转出来时,顺手算出哪些素材是 AI 生成的。算出来、不存:AI 与否是素材的属性、
        不是时间线的,存进序列就得在素材变了的时候跟着改。在这一层算而不在序列领域里算:序列域去问素材域
        的话,两个包就互相 import 了(素材删除要回头动片段)。"""
        model = handler(value)
        state = sqlalchemy_inspect(value, raiseerr=False)
        session = state.session if state is not None else None
        if session is not None:
            from app.domain.assets.provenance import ai_generated_asset_ids

            used = {clip.asset_id for track in model.tracks for clip in track.clips if clip.asset_id}
            model.ai_asset_ids = sorted(ai_generated_asset_ids(session, used))
        return model


class AppendAssetRequest(ApiModel):
    """把整段素材接到它那种轨道的末尾(画板时间线格的连线,ADR 0030)。"""

    asset_id: str


class InsertClipRequest(ApiModel):
    track_id: str
    asset_id: str
    timeline_start: float = 0.0
    src_in: float = 0.0
    src_out: float
    #: 插入模式:落点之后的同轨片段让位。False 是覆盖 —— 落点盖住的部分从别的片段上裁掉。
    ripple: bool = False


class MoveClipRequest(ApiModel):
    timeline_start: float
    track_id: str | None = None
    #: 同 InsertClipRequest.ripple。
    ripple: bool = False
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class ClipMoveEntry(ApiModel):
    clip_id: str
    timeline_start: float
    track_id: str | None = None


class ClipIdsRequest(ApiModel):
    """多选批量操作的通用入参:一次手势一条操作,撤销一步全部还原。"""

    clip_ids: list[str] = Field(min_length=1)
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class RippleDeleteClipsRequest(ClipIdsRequest):
    """多选后一次波纹删除。"""

    #: 波纹影响所有未锁定的轨(这段时间从整条时间线上拿掉);默认只动被删片段和链接组员自己的轨。
    all_tracks: bool = False


class DuplicateClipsRequest(ApiModel):
    """复制几段片段(复制粘贴、Alt 拖复制):位置之外的一切照原样,放下是覆盖,整批一步撤销。"""

    clip_ids: list[str] = Field(min_length=1, max_length=2000)
    #: 整组副本的起点(秒);不给就紧接在原片段组的末尾之后。
    timeline_start: float | None = Field(default=None, ge=0)
    #: 整组放到这条轨上;不给就各回各的原轨。
    track_id: str | None = None


class MoveClipsBatchRequest(ApiModel):
    """框选后整组拖动。没有 ripple —— 一组片段要"挤开"什么没有唯一解,组拖按覆盖语义。"""

    moves: list[ClipMoveEntry] = Field(min_length=1)
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class TrimClipRequest(ApiModel):
    timeline_start: float
    src_in: float
    src_out: float
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class ExportRequest(ApiModel):
    """导出参数;整个 body 可省略(老调用方/工作流节点按默认档导出)。"""

    resolution: Literal["original", "1080p", "720p", "480p"] = "original"
    fps: float | None = Field(default=None, ge=1, le=120)
    quality: Literal["high", "standard", "compact"] = "standard"
    #: 成片里有数字人片段时,片头和画面一角加「AI 生成」(ADR 0028 §5)。**默认开、允许关**;关了照样写 AIGC 隐式标识。
    ai_label: bool = True


class CutClipRangeRequest(ApiModel):
    src_start: float
    src_end: float


class CutClipRangesRequest(ApiModel):
    ranges: list[CutClipRangeRequest] = Field(min_length=1)
    #: 链接组员(分离出去的音频)剪掉同样的时间;False = 只剪这一段。
    linked: bool = True


class ClipRangeCutsRequest(ApiModel):
    clip_id: str
    ranges: list[CutClipRangeRequest] = Field(min_length=1)


class CutClipRangesBatchRequest(ApiModel):
    """一次字幕裁切手势涉及的全部片段。整批只产生一条时间线操作。"""

    cuts: list[ClipRangeCutsRequest] = Field(min_length=1)
    #: 链接组员(分离出去的音频)剪掉同样的时间;False = 只剪点到的这些段。字幕轨总是跟着左移。
    linked: bool = True


class SplitClipRequest(ApiModel):
    src_time: float
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class SplitClipPointsRequest(ApiModel):
    src_times: list[float] = Field(min_length=1)
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class ClipPointSplitsRequest(ApiModel):
    clip_id: str
    src_times: list[float] = Field(min_length=1)


class SplitClipPointsBatchRequest(ApiModel):
    """一次字幕切分手势涉及的全部片段。整批只产生一条时间线操作。"""

    splits: list[ClipPointSplitsRequest] = Field(min_length=1)
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class MoveTrackRequest(ApiModel):
    direction: str = Field(pattern="^(up|down)$")


class SubtitleCueInput(ApiModel):
    text: str
    timeline_start: float
    duration: float


class GenerateSubtitlesRequest(ApiModel):
    track_id: str
    cues: list[SubtitleCueInput] = Field(min_length=1)
    #: 先清掉这条字幕轨上原有的字幕(「重新生成」),和铺新的一起是撤销栈上的一步。
    replace: bool = False


class SubtitleImportOut(ApiModel):
    """导入 .srt / .vtt 的结果:落到了哪条轨、落了几条、几条因为在时间线内容之外没落,以及改完的整条序列。"""

    track_id: str
    imported: int
    dropped: int
    sequence: SequenceOut


class ReplaceClipMediaRequest(ApiModel):
    """把片段换成另一份素材,位置、时长、属性都不动。`clip_ids` 点名;`from_asset_id` = 这条时间线上用着那份素材的全部片段。"""

    asset_id: str
    clip_ids: list[str] = Field(default_factory=list, max_length=2000)
    from_asset_id: str = ""


class ClipAudioRequest(ApiModel):
    """对片段做声音处理,做完直接换到时间线上:降噪 / 只留人声 / 拆成人声和背景音。"""

    action: Literal["denoise", "isolate_voice", "separate"]


class SetSubtitleStyleRequest(ApiModel):
    style: dict


class SetTrackStateRequest(ApiModel):
    muted: bool | None = None
    hidden: bool | None = None
    locked: bool | None = None
    solo: bool | None = None
    duck: bool | None = None


class AddTrackRequest(ApiModel):
    kind: str = Field(pattern="^(video|audio|subtitle)$")
    #: 放在第几行(0 = 最上面)。不给:视频轨放最上面(盖在所有画面之上),音频 / 字幕轨放最下面。
    index: int | None = Field(default=None, ge=0)


class SetClipEffectsRequest(ApiModel):
    effects: dict = Field(default_factory=dict)


class SetClipSpeedRequest(ApiModel):
    speed: float = Field(ge=0.25, le=4.0)
    #: 变速后时长变了:True(默认)推开 / 拉回同轨后续片段;False 后面的不动,慢放会盖住下一段时拒绝。
    ripple: bool = True
    #: 链接组(视频与分离出的音频)一起动;False = 只动这一段(「临时解链」)。
    linked: bool = True


class SetClipGainRequest(ApiModel):
    gain: float = Field(ge=0.0, le=4.0)
    muted: bool = False


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


class SequenceFrameRequest(ApiModel):
    """把时间线在某一时刻的合成画面存成一份新素材。"""

    at: float = 0
