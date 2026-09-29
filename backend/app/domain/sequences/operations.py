"""时间线编辑操作的入口:唯一那张编辑操作表,以及各子模块算子的统一出口。

算子按职责住在同包的子模块里:放置(placement)、轨道(tracks)、文本与字幕(text)、
片段属性(clip_properties)、切分(cutting),共用底座在 _timeline。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.sequences._timeline import (
    INHERITED_CLIP_FIELDS,
    MIN_CUT_REMAINDER,
    RESTORABLE_CLIP_FIELDS,
    _record_operation,
    _require_sequence,
    _validate_clip_range,
    timeline_span,
)
from app.domain.sequences.clip_properties import (
    DetachClipAudio,
    SetClipEffects,
    SetClipGain,
    SetClipSpeed,
    SetClipTransform,
    SetSequenceReframe,
    clean_transform,
    detach_clip_audio,
    set_clip_effects,
    set_clip_gain,
    set_clip_speed,
    set_clip_transform,
    set_sequence_reframe,
)
from app.domain.sequences.cutting import (
    ClipPointSplits,
    ClipRangeCuts,
    CutClipRange,
    CutClipRanges,
    CutClipRangesBatch,
    SplitClip,
    SplitClipPoints,
    SplitClipPointsBatch,
    cut_clip_range,
    cut_clip_ranges,
    cut_clip_ranges_batch,
    split_clip,
    split_clip_at_points,
    split_clip_points_batch,
)
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.sequences.placement import (
    ClipMove,
    DeleteClip,
    DeleteClipsBatch,
    InsertClip,
    MoveClip,
    MoveClipsBatch,
    RippleDeleteClip,
    RippleDeleteClipsBatch,
    TrimClip,
    delete_clip,
    delete_clips_batch,
    insert_clip,
    move_clip,
    move_clips_batch,
    ripple_delete_clip,
    ripple_delete_clips_batch,
    trim_clip,
)
from app.domain.sequences.text import (
    GenerateSubtitles,
    InsertTextClip,
    SetClipText,
    SetClipTextsBatch,
    SetSubtitleStyle,
    clean_subtitle_style,
    generate_subtitles,
    insert_text_clip,
    set_clip_text,
    set_clip_texts_batch,
    set_subtitle_style,
)
from app.domain.sequences.tracks import (
    AddTrack,
    MoveTrack,
    RemoveTrack,
    SetTrackState,
    add_track,
    move_track,
    remove_track,
    set_track_state,
)
from app.media.render_plan import TRANSFORM_BOUNDS, TRANSFORM_DEFAULTS

# 统一再导出:调用方和编辑操作表都只认这一个入口,子模块怎么拆不该波及它们。
__all__ = [
    "EDIT_OP_KINDS",
    "INHERITED_CLIP_FIELDS",
    "MIN_CUT_REMAINDER",
    "RESTORABLE_CLIP_FIELDS",
    "TRANSFORM_BOUNDS",
    "TRANSFORM_DEFAULTS",
    "AddTrack",
    "ClipMove",
    "ClipPointSplits",
    "ClipRangeCuts",
    "CutClipRange",
    "CutClipRanges",
    "CutClipRangesBatch",
    "DeleteClip",
    "DeleteClipsBatch",
    "DetachClipAudio",
    "GenerateSubtitles",
    "InsertClip",
    "InsertTextClip",
    "MoveClip",
    "MoveClipsBatch",
    "MoveTrack",
    "RemoveTrack",
    "RippleDeleteClip",
    "RippleDeleteClipsBatch",
    "SequenceDomainError",
    "SequenceNotFound",
    "SetClipEffects",
    "SetClipGain",
    "SetClipSpeed",
    "SetClipText",
    "SetClipTextsBatch",
    "SetClipTransform",
    "SetSequenceReframe",
    "SetSubtitleStyle",
    "SetTrackState",
    "SplitClip",
    "SplitClipPoints",
    "SplitClipPointsBatch",
    "TrimClip",
    "_record_operation",
    "_require_sequence",
    "_validate_clip_range",
    "add_track",
    "apply_edit_operations",
    "clean_subtitle_style",
    "clean_transform",
    "cut_clip_range",
    "cut_clip_ranges",
    "cut_clip_ranges_batch",
    "delete_clip",
    "delete_clips_batch",
    "detach_clip_audio",
    "generate_subtitles",
    "insert_clip",
    "insert_text_clip",
    "move_clip",
    "move_clips_batch",
    "move_track",
    "remove_track",
    "ripple_delete_clip",
    "ripple_delete_clips_batch",
    "set_clip_effects",
    "set_clip_gain",
    "set_clip_speed",
    "set_clip_text",
    "set_clip_texts_batch",
    "set_clip_transform",
    "set_sequence_reframe",
    "set_subtitle_style",
    "set_track_state",
    "split_clip",
    "split_clip_at_points",
    "split_clip_points_batch",
    "timeline_span",
    "trim_clip",
]


#: 一组时间线操作的种类。**这是"能对时间线做什么"的清单**,不是某一个界面的清单 ——
#: 智能体的 edit_timeline、工作流的时间线节点、将来任何别的入口,认的都是这一份。
#: **「能对时间线做什么」的唯一那份数据。**
#:
#: 智能体的 `edit_timeline`、工作流的时间线节点、将来任何别的入口,认的都是这一份;
#: `EDIT_OP_KINDS` 和派发都从它算出来,所以**两者不可能漂**。
#:
#: 此前清单和派发是两份手写的元组与 `if/elif`,恰好对得上,而没有任何东西比对它们 ——
#: 加一项忘了另一边:加在元组里 → 运行时"不认识的时间线操作";加在派发里 → 校验先把它拦掉。
#: 这正是"两个数碰巧相等所以一直没人发现"那个形状。
#:
#: 而且它**当时不是全集**:28 个变更操作里只列了 10 个。于是"把这段调成 1.5 倍速"、
#: "把这条字幕的样式改一下"在对话里和工作流里都做不到 —— 而领域层做得到。
#: 缺席的表现是**功能缺失**,不是报错,用户只会觉得"智能体不会调速"。
_EDIT_OPS: dict[str, tuple[type, Any]] = {
    "insert_clip": (InsertClip, insert_clip),
    "move_clip": (MoveClip, move_clip),
    "move_clips_batch": (MoveClipsBatch, move_clips_batch),
    "trim_clip": (TrimClip, trim_clip),
    "split_clip": (SplitClip, split_clip),
    "delete_clip": (DeleteClip, delete_clip),
    "ripple_delete_clip": (RippleDeleteClip, ripple_delete_clip),
    "cut_clip_range": (CutClipRange, cut_clip_range),
    "add_track": (AddTrack, add_track),
    "remove_track": (RemoveTrack, remove_track),
    "set_clip_effects": (SetClipEffects, set_clip_effects),
    "set_clip_transform": (SetClipTransform, set_clip_transform),
    "set_clip_speed": (SetClipSpeed, set_clip_speed),
    "set_clip_gain": (SetClipGain, set_clip_gain),
    "detach_clip_audio": (DetachClipAudio, detach_clip_audio),
    # 字幕条就是一段没有素材的文本片段。它此前不在清单里,于是"给这个视频加字幕"在对话里
    # 根本做不到 —— 而那是这个应用最常被要求做的几件事之一。
    "insert_text_clip": (InsertTextClip, insert_text_clip),
    "set_clip_text": (SetClipText, set_clip_text),
    "set_subtitle_style": (SetSubtitleStyle, set_subtitle_style),
    "set_sequence_reframe": (SetSequenceReframe, set_sequence_reframe),
}

EDIT_OP_KINDS = tuple(_EDIT_OPS)



def apply_edit_operations(db: Session, sequence_id: str, operations: list[dict[str, Any]]) -> int:
    """把一组 `{kind, ...args}` 应用到一条序列上,返回应用了几条。

    **住在这里而不是某个入口里。** 这段派发此前长在 domain/agent/confirmations 里 ——
    它和智能体没有关系,那只是第一个用到它的地方。工作流要用同一套时,要么 import 智能体域
    (方向反了),要么抄一份(于是两处会漂)。
    """
    applied = 0
    for operation in operations:
        kind = operation["kind"]
        spec = _EDIT_OPS.get(kind)
        if spec is None:
            raise SequenceDomainError("seqErr_unknownOp", kind=kind)
        request, handler = spec
        args = {key: value for key, value in operation.items() if key != "kind"}
        #: `add_track` 的轨道类型走 `track_kind`:操作自己的名字已经占了 `kind`。
        if kind == "add_track":
            args = {"kind": str(args.get("track_kind", "video"))}
        handler(db, sequence_id, request(**args))
        applied += 1
    return applied
