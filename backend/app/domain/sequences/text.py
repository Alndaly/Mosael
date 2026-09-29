"""文本与字幕:字幕条、花字、改文本与序列级字幕样式。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, Track
from app.domain.sequences._timeline import (
    _clip_payload,
    _record_operation,
    _require_clip,
    _require_sequence,
    _validate_clip_range,
)
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound


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
    actor_id: str | None = None


def generate_subtitles(db: Session, sequence_id: str, op: GenerateSubtitles) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
    if track.kind != "subtitle":
        raise SequenceDomainError("Subtitles need a subtitle track")
    created: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for text, start, duration in op.cues:
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
        clip = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=track.id,
            asset_id=None,
            timeline_start=float(start),
            src_in=0,
            src_out=float(duration),
            text_override=cleaned,
        )
        db.add(clip)
        db.flush()
        created.append(_clip_payload(clip))
    if not created:
        raise SequenceDomainError("No subtitle cues to insert")
    _record_operation(
        db,
        sequence,
        kind="insert_clips_batch",
        payload={"created": created},
        summary={"operation": "insert_clips_batch", "count": len(created)},
        actor_id=op.actor_id,
    )
    return sequence


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
    if op.duration <= 0:
        raise SequenceDomainError("Duration must be positive")
    _validate_clip_range(op.timeline_start, 0, op.duration)

    clip = Clip(
        workspace_id=sequence.workspace_id,
        sequence_id=sequence.id,
        track_id=track.id,
        asset_id=None,
        timeline_start=op.timeline_start,
        src_in=0,
        src_out=op.duration,
        text_override=op.text,
    )
    db.add(clip)
    db.flush()
    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload=_clip_payload(clip),
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
            return max(lo, min(hi, float(raw.get(key, _SUBTITLE_DEFAULTS[key]))))
        except (TypeError, ValueError):
            return float(_SUBTITLE_DEFAULTS[key])

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
