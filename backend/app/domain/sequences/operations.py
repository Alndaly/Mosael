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
from app.domain.sequences import history, op_args
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
    "edit_operation_usage",
    "normalized_edit_operations",
    "parse_edit_operations",
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
#:
#: 每一项是 (入参模型, 处理函数):入参模型(op_args)认 JSON 里的参数、生成给智能体看的说明,再造出领域的请求体。
_EDIT_OPS: dict[str, tuple[type[op_args.OpArgs], Any]] = {
    "insert_clip": (op_args.InsertClipArgs, insert_clip),
    "move_clip": (op_args.MoveClipArgs, move_clip),
    "move_clips_batch": (op_args.MoveClipsBatchArgs, move_clips_batch),
    "trim_clip": (op_args.TrimClipArgs, trim_clip),
    "split_clip": (op_args.SplitClipArgs, split_clip),
    "delete_clip": (op_args.DeleteClipArgs, delete_clip),
    "ripple_delete_clip": (op_args.RippleDeleteClipArgs, ripple_delete_clip),
    "cut_clip_range": (op_args.CutClipRangeArgs, cut_clip_range),
    #: 同一段上连剪几刀。逐条 cut_clip_range 做不到:第一刀之后原片段就换成了切出来的新片段,第二刀找不到它。
    "cut_clip_ranges_batch": (op_args.CutClipRangesBatchArgs, cut_clip_ranges_batch),
    "add_track": (op_args.AddTrackArgs, add_track),
    "remove_track": (op_args.RemoveTrackArgs, remove_track),
    "set_track_state": (op_args.SetTrackStateArgs, set_track_state),
    "detach_clip_audio": (op_args.DetachClipAudioArgs, detach_clip_audio),
    "set_clip_effects": (op_args.SetClipEffectsArgs, set_clip_effects),
    "set_clip_transform": (op_args.SetClipTransformArgs, set_clip_transform),
    "set_clip_speed": (op_args.SetClipSpeedArgs, set_clip_speed),
    "set_clip_gain": (op_args.SetClipGainArgs, set_clip_gain),
    "set_sequence_reframe": (op_args.SetSequenceReframeArgs, set_sequence_reframe),
    # 字幕条就是一段没有素材的文本片段。它此前不在清单里,于是"给这个视频加字幕"在对话里
    # 根本做不到 —— 而那是这个应用最常被要求做的几件事之一。
    "insert_text_clip": (op_args.InsertTextClipArgs, insert_text_clip),
    #: 一整条字幕一次铺上去、一次改完文字:一条操作、一步撤销(逐条插 N 条就是 N 次撤销)。
    "generate_subtitles": (op_args.GenerateSubtitlesArgs, generate_subtitles),
    "set_clip_text": (op_args.SetClipTextArgs, set_clip_text),
    "set_clip_texts_batch": (op_args.SetClipTextsBatchArgs, set_clip_texts_batch),
    "set_subtitle_style": (op_args.SetSubtitleStyleArgs, set_subtitle_style),
    "undo": (op_args.HistoryArgs, history.undo_step),
    "redo": (op_args.HistoryArgs, history.redo_step),
}

EDIT_OP_KINDS = tuple(_EDIT_OPS)


def edit_operation_usage() -> list[str]:
    """每种操作一行 `kind(参数…)` —— 智能体工具说明和 docs/MCP.md 都从这里生成,和校验是同一份模型。"""
    return [op_args.usage(kind, model) for kind, (model, _handler) in _EDIT_OPS.items()]


def parse_edit_operations(operations: Any) -> list[tuple[str, op_args.OpArgs]]:
    """一组 `{kind, ...args}` 逐条认参数,不碰数据库。不认识的操作、错的参数名、缺的必填、不是有限数的数都在这里拒,
    报错里带着正确写法。"""
    if not isinstance(operations, list) or not operations:
        raise SequenceDomainError("seqErr_opsEmpty")
    parsed = []
    for operation in operations:
        if not isinstance(operation, dict):
            raise SequenceDomainError("seqErr_opNotObject")
        kind = operation.get("kind")
        spec = _EDIT_OPS.get(kind) if isinstance(kind, str) else None
        if spec is None:
            raise SequenceDomainError("seqErr_unknownOp", kind=kind)
        args = {key: value for key, value in operation.items() if key != "kind"}
        parsed.append((kind, op_args.parse(kind, spec[0], args)))
    return parsed


def normalized_edit_operations(operations: Any) -> list[dict[str, Any]]:
    """认过参数、补齐缺省值之后的样子 —— 确认卡存这一份:卡上写的、批准后执行的,就是校验过的那一份。"""
    return [{"kind": kind, **args.model_dump()} for kind, args in parse_edit_operations(operations)]


def apply_edit_operations(
    db: Session, sequence_id: str, operations: list[dict[str, Any]], *, actor_id: str | None = None
) -> int:
    """把一组 `{kind, ...args}` 应用到一条序列上,返回应用了几条。**先整组认完参数再动手** —— 第三条写错了参数名,
    前两条不该已经做了一半。`actor_id` 是这些编辑算在谁头上(确认卡是批准的那个人)。

    **住在这里而不是某个入口里。** 这段派发此前长在 domain/agent/confirmations 里 ——
    它和智能体没有关系,那只是第一个用到它的地方。工作流要用同一套时,要么 import 智能体域
    (方向反了),要么抄一份(于是两处会漂)。
    """
    parsed = parse_edit_operations(operations)
    for kind, args in parsed:
        handler = _EDIT_OPS[kind][1]
        handler(db, sequence_id, args.to_request(actor_id))
    return len(parsed)
