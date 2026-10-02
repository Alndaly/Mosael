"""文本与字幕:字幕条、花字、改文本与序列级字幕样式。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, Track
from app.domain.sequences._timeline import (
    _record_operation,
    _require_clip,
    _require_sequence,
    _validate_clip_range,
    finite_number,
)
from app.domain.sequences.coverage import clear_range, clip_end, clips_on_track
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.sequences.journal import Journal


@dataclass(frozen=True)
class InsertTextClip:
    """A subtitle/text clip: no asset, text lives in text_override."""

    track_id: str
    text: str
    timeline_start: float
    duration: float
    actor_id: str | None = None


@dataclass(frozen=True)
class GenerateSubtitles:
    """Batch-insert many subtitle cues onto one subtitle track in a single op (一键生成字幕
    from the transcript). cues = tuple of (text, timeline_start, duration)."""

    track_id: str
    cues: tuple[tuple[str, float, float], ...]
    #: 先清掉这条字幕轨上原有的字幕再铺(「重新生成」)。和铺新的记成撤销栈上的一步。
    #: 此前再点一次「生成字幕」,同一条轨上每一句都叠成两份(探针 P5)。
    replace: bool = False
    actor_id: str | None = None


#: 时间线上一条字幕最晚能从第几秒开始 —— 没有任何内容可对照时的兜底(一条一天长的时间线已经不是剪辑了)。
_MAX_CUE_START = 24 * 3600.0
#: 字幕比内容末尾多出这么一点不算越界(转写的句尾常常比素材长几十毫秒)。
_CUE_END_SLACK = 0.05


def generate_subtitles(db: Session, sequence_id: str, op: GenerateSubtitles) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
    if track.kind != "subtitle":
        raise SequenceDomainError("Subtitles need a subtitle track")
    cues = _checked_cues(db, sequence, op.cues)
    journal = Journal(db, sequence)
    if op.replace:
        # 「重新生成」:先清掉这条轨上原有的字幕,和铺新的记在同一份改动日志里(一步撤销)。放下即覆盖只盖住
        # 新字幕落点上的那几条 —— 重新转写后断句变了,落在新字幕空隙里的旧字幕还会留着。
        for old in clips_on_track(db, track.id):
            journal.delete(old)
    created = 0
    seen: set[tuple[float, str]] = set()
    for text, start, duration in cues:
        cleaned = (text or "").strip()
        if not cleaned or duration <= 0 or start < 0:
            continue
        # Drop exact duplicate cues (same start + text) — projectTranscript emits a segment
        # once per clip that references its asset, so a reused/overlapping clip would otherwise
        # insert every subtitle twice.
        key = (round(float(start), 3), cleaned)
        if key in seen:
            continue
        seen.add(key)
        clip = journal.create(
            Clip(
                workspace_id=sequence.workspace_id,
                sequence_id=sequence.id,
                track_id=track.id,
                asset_id=None,
                timeline_start=float(start),
                src_in=0,
                src_out=float(duration),
                text_override=cleaned,
            )
        )
        # 和放下一段片段同一条规矩:同一条字幕轨上不叠着两条字幕,后来的这条盖住落点上的。
        clear_range(journal, track.id, clip.timeline_start, clip_end(clip), keep={clip.id})
        created += 1
    if not created:
        raise SequenceDomainError("No subtitle cues to insert")
    _record_operation(
        db,
        sequence,
        kind="insert_clips_batch",
        payload={"changes": journal.entries},
        summary={"operation": "insert_clips_batch", "count": created},
        actor_id=op.actor_id,
    )
    return sequence


def _checked_cues(
    db: Session, sequence: Sequence, cues: tuple[tuple[str, float, float], ...]
) -> list[tuple[str, float, float]]:
    """字幕的时间先验过再落库:非有限数直接拒;起点落在时间线内容之外的拒(说是第几条);
    尾巴超出内容末尾的截到末尾。时间线上还没有任何内容时,只拦明显荒谬的起点。

    此前一条起点 1e9 秒的字幕照样 200 —— 时间线一下子变成三十年长,导出和缩放全部错乱。
    """
    import math

    # 按库查每条轨的末尾(coverage.clips_on_track),不经 append.track_end:append 要 import 编辑算子,
    # 而这里就是编辑算子 —— 那是一个环。
    content_end = max(
        (
            clip_end(clip)
            for track in sequence.tracks or []
            if track.kind != "subtitle" and track.role != "dub"
            for clip in clips_on_track(db, track.id)
        ),
        default=0.0,
    )
    limit = content_end if content_end > 0 else _MAX_CUE_START
    checked: list[tuple[str, float, float]] = []
    for index, (text, start, duration) in enumerate(cues, start=1):
        if not (math.isfinite(start) and math.isfinite(duration)):
            raise SequenceDomainError("seqErr_cueNotFinite", index=index)
        if start >= limit:
            raise SequenceDomainError("seqErr_cueOutsideTimeline", index=index, start=f"{start:g}", end=f"{limit:g}")
        if content_end > 0 and start + duration > content_end + _CUE_END_SLACK:
            duration = content_end - start
        checked.append((text, start, duration))
    return checked


def insert_text_clip(db: Session, sequence_id: str, op: InsertTextClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
    # 字幕轨 = 序列级统一样式的底部字幕;video 轨 = 花字(每条自带样式、transform 定位)。
    if track.kind not in ("subtitle", "video"):
        raise SequenceDomainError("Text clips can only be placed on subtitle or video tracks")
    if not op.text.strip():
        raise SequenceDomainError("Text must not be empty")
    if finite_number("duration", op.duration) <= 0:
        raise SequenceDomainError("Duration must be positive")
    _validate_clip_range(op.timeline_start, 0, op.duration)

    journal = Journal(db, sequence)
    clip = journal.create(
        Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=track.id,
            asset_id=None,
            timeline_start=op.timeline_start,
            src_in=0,
            src_out=op.duration,
            text_override=op.text,
        )
    )
    # 覆盖:同轨落点上已有的字幕 / 花字被盖住的部分裁掉(见 coverage)。
    clear_range(journal, track.id, clip.timeline_start, clip_end(clip), keep={clip.id})
    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "insert_clip", "clip_id": clip.id, "text": True},
        actor_id=op.actor_id,
    )
    return sequence


@dataclass(frozen=True)
class SetClipText:
    clip_id: str
    text: str
    actor_id: str | None = None


def set_clip_text(db: Session, sequence_id: str, op: SetClipText) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not op.text.strip():
        raise SequenceDomainError("Text must not be empty")
    previous = clip.text_override
    clip.text_override = op.text
    _record_operation(
        db,
        sequence,
        kind="set_clip_text",
        payload={"clip_id": clip.id, "text": op.text, "previous": previous},
        summary={"operation": "set_clip_text", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


@dataclass(frozen=True)
class SetClipTextsBatch:
    """Retext many clips as ONE operation. Translating a track clip-by-clip produced N requests,
    N revisions and N undo steps, and a failure partway through left the track half-translated
    with no single point to revert to."""

    texts: tuple[tuple[str, str], ...]  # (clip_id, text)
    actor_id: str | None = None


def set_clip_texts_batch(db: Session, sequence_id: str, op: SetClipTextsBatch) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    if not op.texts:
        raise SequenceDomainError("No texts to apply")
    entries = []
    for clip_id, text in op.texts:
        clip = _require_clip(db, sequence_id, clip_id)
        if not text.strip():
            raise SequenceDomainError("Text must not be empty")
        entries.append({"clip_id": clip.id, "text": text, "previous": clip.text_override})
    # Validate every clip BEFORE mutating any: a bad id halfway through would otherwise leave
    # the track partly rewritten, which is the exact failure this operation exists to remove.
    for entry in entries:
        _require_clip(db, sequence_id, entry["clip_id"]).text_override = entry["text"]
    _record_operation(
        db,
        sequence,
        kind="set_clip_texts_batch",
        payload={"entries": entries},
        summary={"operation": "set_clip_texts_batch", "count": len(entries)},
        actor_id=op.actor_id,
    )
    return sequence


_SUBTITLE_POSITIONS = ("bottom", "center", "top")
_SUBTITLE_DEFAULTS: dict[str, Any] = {
    "font_size": 32.0,
    "color": "#ffffff",
    "bg_color": "#000000",
    "bg_opacity": 0.5,
    "bold": True,
    "position": "bottom",
    "offset": 8.0,  # % of frame height from the edge (or from center for position=center)
    "show_speaker": False,
    "font_family": "",
    "font_id": "",
}


def clean_subtitle_style(raw: dict[str, Any]) -> dict[str, Any]:
    """归一化字幕样式:补默认、钳制范围、白名单枚举(参考前身项目 SubtitleStyle)。"""
    raw = raw or {}

    def num(key: str, lo: float, hi: float) -> float:
        try:
            value = float(raw.get(key, _SUBTITLE_DEFAULTS[key]))
        except (TypeError, ValueError):
            return float(_SUBTITLE_DEFAULTS[key])
        # NaN 过 min/max 会被钳成上限;非有限的和非数字一样回落默认。
        return max(lo, min(hi, value)) if math.isfinite(value) else float(_SUBTITLE_DEFAULTS[key])

    position = raw.get("position", "bottom")
    return {
        "font_size": num("font_size", 10, 160),
        "color": str(raw.get("color", "#ffffff"))[:9],
        "bg_color": str(raw.get("bg_color", "#000000"))[:9],
        "bg_opacity": num("bg_opacity", 0, 1),
        "bold": bool(raw.get("bold", True)),
        "position": position if position in _SUBTITLE_POSITIONS else "bottom",
        "offset": num("offset", 0, 45),
        "show_speaker": bool(raw.get("show_speaker", False)),
        # A CSS stack for the preview; export narrows it to the one family libass accepts.
        "font_family": str(raw.get("font_family", "") or "")[:200],
        # Set only when the family comes from an uploaded font — export needs the id to find
        # the file, since an uploaded face is not installed on the rendering machine.
        "font_id": str(raw.get("font_id", "") or "")[:64],
    }


@dataclass(frozen=True)
class SetSubtitleStyle:
    style: dict[str, Any]
    actor_id: str | None = None


def set_subtitle_style(db: Session, sequence_id: str, op: SetSubtitleStyle) -> Sequence:
    """字幕全局样式(字号/颜色/背景/位置等),存在序列上。"""
    sequence = _require_sequence(db, sequence_id)
    previous = dict(sequence.subtitle_style or {})
    sequence.subtitle_style = clean_subtitle_style(op.style)
    _record_operation(
        db,
        sequence,
        kind="set_subtitle_style",
        payload={"style": sequence.subtitle_style, "previous": previous},
        summary={"operation": "set_subtitle_style"},
        actor_id=op.actor_id,
    )
    return sequence
