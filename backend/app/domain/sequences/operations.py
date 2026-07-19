from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, SequenceOperation, SequenceRevision, Track


class SequenceDomainError(ValueError):
    pass


@dataclass(frozen=True)
class InsertClip:
    track_id: str
    asset_id: str
    timeline_start: float
    src_in: float
    src_out: float
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveClip:
    clip_id: str
    timeline_start: float
    track_id: str | None = None
    # Insert-edit (DaVinci "insert" mode): push destination-track clips at or
    # after the drop point right by this clip's duration to make room.
    ripple: bool = False
    actor_id: str | None = None


@dataclass(frozen=True)
class TrimClip:
    clip_id: str
    timeline_start: float
    src_in: float
    src_out: float
    actor_id: str | None = None


@dataclass(frozen=True)
class DeleteClip:
    clip_id: str
    actor_id: str | None = None


@dataclass(frozen=True)
class CutClipRange:
    """Remove a source-time range from a clip (transcript-driven edit).

    The clip splits into a left part (original position) and a right part
    that ripples left to close the gap. Cuts touching an edge trim instead;
    a cut covering everything deletes the clip.
    """

    clip_id: str
    src_start: float
    src_end: float
    actor_id: str | None = None


def insert_clip(db: Session, sequence_id: str, op: InsertClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    asset = db.get(Asset, op.asset_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceDomainError("Asset not found")
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)

    clip = Clip(
        workspace_id=sequence.workspace_id,
        sequence_id=sequence.id,
        track_id=track.id,
        asset_id=asset.id,
        timeline_start=op.timeline_start,
        src_in=op.src_in,
        src_out=op.src_out,
    )
    db.add(clip)
    db.flush()  # materialize clip.id so the operation payload can invert
    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload={
            "clip_id": clip.id,
            "track_id": op.track_id,
            "asset_id": op.asset_id,
            "timeline_start": op.timeline_start,
            "src_in": op.src_in,
            "src_out": op.src_out,
        },
        summary={"operation": "insert_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def move_clip(db: Session, sequence_id: str, op: MoveClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if op.timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")

    previous_track_id = clip.track_id
    target_track_id = op.track_id or clip.track_id
    if target_track_id != clip.track_id:
        target = db.get(Track, target_track_id)
        source = db.get(Track, clip.track_id)
        if target is None or target.sequence_id != sequence_id:
            raise SequenceDomainError("Target track not found")
        if source is not None and target.kind != source.kind:
            raise SequenceDomainError("Target track kind does not match clip track kind")
        clip.track_id = target.id

    previous_start = clip.timeline_start
    clip.timeline_start = op.timeline_start

    shifted: list[dict[str, Any]] = []
    if op.ripple:
        # Insert edit: make room for the clip at its new spot by pushing the
        # downstream clips right — but only by the actual OVERLAP, and only when
        # there is a real collision. Shifting everyone by the full clip duration
        # (regardless of overlap) exploded the timeline on any nudge.
        duration = (clip.src_out - clip.src_in) / (clip.speed or 1)
        moved_end = op.timeline_start + duration
        downstream = list(
            db.scalars(
                select(Clip).where(
                    Clip.track_id == clip.track_id,
                    Clip.id != clip.id,
                    Clip.timeline_start >= op.timeline_start - 1e-9,
                )
            )
        )
        overlap = moved_end - min((c.timeline_start for c in downstream), default=moved_end)
        if downstream and overlap > 1e-9:
            for other in downstream:  # shift all downstream by the same amount → gaps preserved
                new_start = other.timeline_start + overlap
                shifted.append(
                    {"clip_id": other.id, "previous_timeline_start": other.timeline_start, "timeline_start": new_start}
                )
                other.timeline_start = new_start

    _record_operation(
        db,
        sequence,
        kind="move_clip",
        payload={
            "clip_id": clip.id,
            "track_id": clip.track_id,
            "timeline_start": op.timeline_start,
            "previous_timeline_start": previous_start,
            "previous_track_id": previous_track_id,
            "shifted": shifted,
        },
        summary={"operation": "move_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def trim_clip(db: Session, sequence_id: str, op: TrimClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)

    previous = {
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    clip.timeline_start = op.timeline_start
    clip.src_in = op.src_in
    clip.src_out = op.src_out
    _record_operation(
        db,
        sequence,
        kind="trim_clip",
        payload={
            "clip_id": clip.id,
            "timeline_start": op.timeline_start,
            "src_in": op.src_in,
            "src_out": op.src_out,
            "previous": previous,
        },
        summary={"operation": "trim_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def delete_clip(db: Session, sequence_id: str, op: DeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)

    payload = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    db.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="delete_clip",
        payload=payload,
        summary={"operation": "delete_clip", "clip_id": payload["clip_id"]},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class RippleDeleteClip:
    """Delete a clip and shift later clips on the same track left to close the gap."""

    clip_id: str
    actor_id: str | None = None


def ripple_delete_clip(db: Session, sequence_id: str, op: RippleDeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    gap = clip.src_out - clip.src_in
    anchor = clip.timeline_start

    original = _clip_payload(clip)
    shifted: list[dict[str, Any]] = []
    followers = db.scalars(
        select(Clip).where(Clip.track_id == clip.track_id, Clip.id != clip.id, Clip.timeline_start >= anchor)
    )
    for other in followers:
        new_start = max(anchor, other.timeline_start - gap)
        if new_start == other.timeline_start:
            continue
        shifted.append(
            {"clip_id": other.id, "previous_timeline_start": other.timeline_start, "timeline_start": new_start}
        )
        other.timeline_start = new_start
    db.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clip",
        payload={"clip_id": original["clip_id"], "original": original, "shifted": shifted},
        summary={"operation": "ripple_delete_clip", "clip_id": original["clip_id"], "shifted": len(shifted)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class AddTrack:
    kind: str  # "video" | "audio"
    actor_id: str | None = None


@dataclass(frozen=True)
class RemoveTrack:
    track_id: str
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveTrack:
    track_id: str
    direction: str  # "up" | "down"
    actor_id: str | None = None


@dataclass(frozen=True)
class SetClipEffects:
    clip_id: str
    effects: dict[str, Any]
    actor_id: str | None = None


def add_track(db: Session, sequence_id: str, op: AddTrack) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    if op.kind not in ("video", "audio", "subtitle"):
        raise SequenceDomainError("Track kind must be video, audio, or subtitle")
    existing = [track for track in sequence.tracks if track.kind == op.kind]
    prefix = {"video": "V", "audio": "A", "subtitle": "S"}[op.kind]
    track = Track(
        sequence_id=sequence.id,
        kind=op.kind,
        name=f"{prefix}{len(existing) + 1}",
        position=max((item.position for item in sequence.tracks), default=-1) + 1,
    )
    db.add(track)
    db.flush()
    _record_operation(
        db,
        sequence,
        kind="add_track",
        payload={"track_id": track.id, "kind": track.kind, "name": track.name, "position": track.position},
        summary={"operation": "add_track", "track_id": track.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def move_track(db: Session, sequence_id: str, op: MoveTrack) -> Sequence:
    """Reorder a track by swapping its position with the neighbour above/below — changes the
    timeline row order and (for video tracks) the compositing z-order (改视频层级)."""
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    ordered = sorted(sequence.tracks, key=lambda item: item.position)
    index = next(i for i, item in enumerate(ordered) if item.id == track.id)
    swap = index - 1 if op.direction == "up" else index + 1
    if swap < 0 or swap >= len(ordered):
        return sequence  # already at the edge — no-op
    other = ordered[swap]
    track_prev, other_prev = track.position, other.position
    track.position, other.position = other_prev, track_prev
    _record_operation(
        db,
        sequence,
        kind="move_track",
        payload={"track_id": track.id, "track_prev": track_prev, "other_id": other.id, "other_prev": other_prev},
        summary={"operation": "move_track", "track_id": track.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def remove_track(db: Session, sequence_id: str, op: RemoveTrack) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if track.clips:
        raise SequenceDomainError("Track must be empty before it can be removed")
    payload = {"track_id": track.id, "kind": track.kind, "name": track.name, "position": track.position}
    db.delete(track)
    _record_operation(
        db,
        sequence,
        kind="remove_track",
        payload=payload,
        summary={"operation": "remove_track", "track_id": payload["track_id"]},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


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
        raise SequenceDomainError("Track not found")
    if track.kind != "subtitle":
        raise SequenceDomainError("Subtitles need a subtitle track")
    created: list[dict[str, Any]] = []
    for text, start, duration in op.cues:
        cleaned = (text or "").strip()
        if not cleaned or duration <= 0 or start < 0:
            continue
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
    db.commit()
    return sequence


def insert_text_clip(db: Session, sequence_id: str, op: InsertTextClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if track.kind != "subtitle":
        raise SequenceDomainError("Text clips can only be placed on subtitle tracks")
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
    db.commit()
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
    db.commit()
    return sequence


@dataclass(frozen=True)
class SetClipSpeed:
    clip_id: str
    speed: float
    actor_id: str | None = None


def set_clip_speed(db: Session, sequence_id: str, op: SetClipSpeed) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not (0.25 <= op.speed <= 4.0):
        raise SequenceDomainError("Speed must be between 0.25 and 4")
    previous = clip.speed
    clip.speed = op.speed
    _record_operation(
        db,
        sequence,
        kind="set_clip_speed",
        payload={"clip_id": clip.id, "speed": op.speed, "previous": previous},
        summary={"operation": "set_clip_speed", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def set_clip_effects(db: Session, sequence_id: str, op: SetClipEffects) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    previous = dict(clip.effects or {})
    clip.effects = op.effects
    _record_operation(
        db,
        sequence,
        kind="set_clip_effect",
        payload={"clip_id": clip.id, "effects": op.effects, "previous": previous},
        summary={"operation": "set_clip_effect", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


_TRANSFORM_DEFAULTS: dict[str, float] = {"scale": 1.0, "x": 0.0, "y": 0.0, "rotation": 0.0, "opacity": 1.0}
_TRANSFORM_BOUNDS: dict[str, tuple[float, float]] = {
    "scale": (0.1, 4.0),
    "x": (-2.0, 2.0),
    "y": (-2.0, 2.0),
    "rotation": (-180.0, 180.0),
    "opacity": (0.0, 1.0),
}


def clean_transform(raw: dict[str, Any]) -> dict[str, float]:
    """归一化片段变换:补默认、转 float、按范围钳制。"""
    out: dict[str, float] = {}
    for key, default in _TRANSFORM_DEFAULTS.items():
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError) as exc:
            raise SequenceDomainError(f"transform.{key} 必须是数字") from exc
        lo, hi = _TRANSFORM_BOUNDS[key]
        out[key] = max(lo, min(hi, value))
    return out


@dataclass(frozen=True)
class SetClipTransform:
    clip_id: str
    transform: dict[str, Any]
    actor_id: str | None = None


def set_clip_transform(db: Session, sequence_id: str, op: SetClipTransform) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    previous = dict(clip.transform or {})
    clip.transform = clean_transform(op.transform)
    _record_operation(
        db,
        sequence,
        kind="set_clip_transform",
        payload={"clip_id": clip.id, "transform": clip.transform, "previous": previous},
        summary={"operation": "set_clip_transform", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


_FILL_MODES = ("cover", "contain", "blur")


@dataclass(frozen=True)
class SetSequenceReframe:
    width: int
    height: int
    fill_mode: str = "cover"
    actor_id: str | None = None


def set_sequence_reframe(db: Session, sequence_id: str, op: SetSequenceReframe) -> Sequence:
    """改画幅(横转竖等):改序列输出宽高 + 填充模式。"""
    sequence = _require_sequence(db, sequence_id)
    if not (16 <= op.width <= 8192 and 16 <= op.height <= 8192):
        raise SequenceDomainError("画幅尺寸需在 16–8192 之间")
    fill_mode = op.fill_mode if op.fill_mode in _FILL_MODES else "cover"
    previous = {"width": sequence.width, "height": sequence.height, "reframe": dict(sequence.reframe or {})}
    sequence.width = int(op.width)
    sequence.height = int(op.height)
    sequence.reframe = {"fill_mode": fill_mode}
    _record_operation(
        db,
        sequence,
        kind="set_sequence_reframe",
        payload={"width": sequence.width, "height": sequence.height, "reframe": sequence.reframe, "previous": previous},
        summary={"operation": "set_sequence_reframe"},
        actor_id=op.actor_id,
    )
    db.commit()
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
}


def clean_subtitle_style(raw: dict[str, Any]) -> dict[str, Any]:
    """归一化字幕样式:补默认、钳制范围、白名单枚举(参考 mibu-video SubtitleStyle)。"""
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
    db.commit()
    return sequence


@dataclass(frozen=True)
class SplitClip:
    """Cut a clip into two at a source-time point — nothing is removed."""

    clip_id: str
    src_time: float
    actor_id: str | None = None


@dataclass(frozen=True)
class SetTrackState:
    track_id: str
    muted: bool | None = None
    locked: bool | None = None
    solo: bool | None = None
    duck: bool | None = None
    actor_id: str | None = None


def split_clip(db: Session, sequence_id: str, op: SplitClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not (clip.src_in + MIN_CUT_REMAINDER < op.src_time < clip.src_out - MIN_CUT_REMAINDER):
        raise SequenceDomainError("Split point must fall inside the clip")

    original = _clip_payload(clip)
    original["gain"], original["speed"], original["effects"] = clip.gain, clip.speed, clip.effects
    common = {
        "workspace_id": sequence.workspace_id,
        "sequence_id": sequence.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "gain": clip.gain,
        "speed": clip.speed,
        "effects": clip.effects,
    }
    db.delete(clip)
    left = Clip(**common, timeline_start=original["timeline_start"], src_in=original["src_in"], src_out=op.src_time)
    right = Clip(
        **common,
        timeline_start=original["timeline_start"] + (op.src_time - original["src_in"]),
        src_in=op.src_time,
        src_out=original["src_out"],
    )
    db.add_all([left, right])
    db.flush()
    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload={
            "clip_id": original["clip_id"],
            "src_time": op.src_time,
            "original": original,
            "created": [_clip_payload(left), _clip_payload(right)],
        },
        summary={"operation": "split_clip", "clip_id": original["clip_id"]},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def set_track_state(db: Session, sequence_id: str, op: SetTrackState) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    previous = {"muted": track.muted, "locked": track.locked, "solo": track.solo, "duck": track.duck}
    if op.muted is not None:
        track.muted = op.muted
    if op.locked is not None:
        track.locked = op.locked
    if op.solo is not None:
        track.solo = op.solo
    if op.duck is not None:
        track.duck = op.duck
    _record_operation(
        db,
        sequence,
        kind="set_track_state",
        payload={
            "track_id": track.id,
            "muted": track.muted,
            "locked": track.locked,
            "solo": track.solo,
            "duck": track.duck,
            "previous": previous,
        },
        summary={"operation": "set_track_state", "track_id": track.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def cut_clip_range(db: Session, sequence_id: str, op: CutClipRange) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    start = max(op.src_start, clip.src_in)
    end = min(op.src_end, clip.src_out)
    if end <= start:
        raise SequenceDomainError("Cut range does not intersect the clip")

    original = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    created: list[dict[str, Any]] = []

    keep_left = start - clip.src_in > MIN_CUT_REMAINDER
    keep_right = clip.src_out - end > MIN_CUT_REMAINDER
    right_start = clip.timeline_start + (start - clip.src_in) if keep_left else clip.timeline_start

    db.delete(clip)
    if keep_left:
        left = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=original["track_id"],
            asset_id=original["asset_id"],
            timeline_start=original["timeline_start"],
            src_in=original["src_in"],
            src_out=start,
        )
        db.add(left)
        db.flush()
        created.append(_clip_payload(left))
    if keep_right:
        right = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=original["track_id"],
            asset_id=original["asset_id"],
            timeline_start=right_start,
            src_in=end,
            src_out=original["src_out"],
        )
        db.add(right)
        db.flush()
        created.append(_clip_payload(right))

    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload={
            "clip_id": original["clip_id"],
            "src_start": start,
            "src_end": end,
            "original": original,
            "created": created,
        },
        summary={"operation": "apply_transcript_edit", "clip_id": original["clip_id"], "created": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class CutClipRanges:
    """Remove several source-time ranges from one clip in a single operation.

    Kept pieces are laid back-to-back from the clip's original position
    (transcript-style ripple). Recorded as apply_transcript_edit so the
    existing original+created undo/redo path applies unchanged.
    """

    clip_id: str
    ranges: tuple[tuple[float, float], ...]
    actor_id: str | None = None


def cut_clip_ranges(db: Session, sequence_id: str, op: CutClipRanges) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)

    clamped = sorted(
        (max(float(start), clip.src_in), min(float(end), clip.src_out))
        for start, end in op.ranges
        if min(float(end), clip.src_out) > max(float(start), clip.src_in)
    )
    if not clamped:
        raise SequenceDomainError("No cut range intersects the clip")
    merged: list[list[float]] = []
    for start, end in clamped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    kept: list[tuple[float, float]] = []
    cursor_src = clip.src_in
    for start, end in merged:
        if start - cursor_src > MIN_CUT_REMAINDER:
            kept.append((cursor_src, start))
        cursor_src = max(cursor_src, end)
    if clip.src_out - cursor_src > MIN_CUT_REMAINDER:
        kept.append((cursor_src, clip.src_out))

    original = _clip_payload(clip)
    created: list[dict[str, Any]] = []
    db.delete(clip)
    timeline_cursor = original["timeline_start"]
    for src_start, src_end in kept:
        piece = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=original["track_id"],
            asset_id=original["asset_id"],
            timeline_start=timeline_cursor,
            src_in=src_start,
            src_out=src_end,
        )
        db.add(piece)
        db.flush()
        created.append(_clip_payload(piece))
        timeline_cursor += src_end - src_start

    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload={
            "clip_id": original["clip_id"],
            "ranges": [[start, end] for start, end in merged],
            "original": original,
            "created": created,
        },
        summary={"operation": "apply_transcript_edit", "clip_id": original["clip_id"], "created": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass
class SplitClipPoints:
    """Split one clip into pieces at several source-time cut points, in a single op.

    Unlike cut_clip_ranges NOTHING is removed — the pieces stay at their original
    timeline positions (transcript 「按句切分」 / 单句独立成片段). Recorded as split_clip
    so the existing original+created undo/redo path applies unchanged.
    """

    clip_id: str
    src_times: tuple[float, ...]
    actor_id: str | None = None


def split_clip_at_points(db: Session, sequence_id: str, op: SplitClipPoints) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    speed = clip.speed or 1

    # Interior points only, sorted; drop any too close to a neighbour or to the clip ends.
    points: list[float] = []
    cursor = clip.src_in
    for value in sorted({float(p) for p in op.src_times}):
        if value - cursor > MIN_CUT_REMAINDER and clip.src_out - value > MIN_CUT_REMAINDER:
            points.append(value)
            cursor = value
    if not points:
        raise SequenceDomainError("No valid split point inside the clip")

    original = _clip_payload(clip)
    original["gain"], original["speed"], original["effects"] = clip.gain, clip.speed, clip.effects
    common = {
        "workspace_id": sequence.workspace_id,
        "sequence_id": sequence.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "gain": clip.gain,
        "speed": clip.speed,
        "effects": clip.effects,
    }
    boundaries = [clip.src_in, *points, clip.src_out]
    db.delete(clip)
    created: list[dict[str, Any]] = []
    for src_start, src_end in zip(boundaries, boundaries[1:]):
        piece = Clip(
            **common,
            # Keep each piece where it already sits on the timeline (speed-adjusted) — a split
            # divides, it must not move anything.
            timeline_start=original["timeline_start"] + (src_start - original["src_in"]) / speed,
            src_in=src_start,
            src_out=src_end,
        )
        db.add(piece)
        db.flush()
        created.append(_clip_payload(piece))

    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload={"clip_id": original["clip_id"], "src_time": points[0], "original": original, "created": created},
        summary={"operation": "split_clip", "clip_id": original["clip_id"], "created": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


MIN_CUT_REMAINDER = 0.05


def _clip_payload(clip: Clip) -> dict[str, Any]:
    payload = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    if clip.text_override is not None:
        payload["text_override"] = clip.text_override
    return payload


def _require_sequence(db: Session, sequence_id: str) -> Sequence:
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise SequenceDomainError("Sequence not found")
    return sequence


def _require_clip(db: Session, sequence_id: str, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence_id:
        raise SequenceDomainError("Clip not found")
    return clip


def _validate_clip_range(timeline_start: float, src_in: float, src_out: float) -> None:
    if timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")
    if src_in < 0:
        raise SequenceDomainError("src_in must be non-negative")
    if src_out <= src_in:
        raise SequenceDomainError("src_out must be greater than src_in")


def _record_operation(
    db: Session,
    sequence: Sequence,
    *,
    kind: str,
    payload: dict[str, Any],
    summary: dict[str, Any],
    actor_id: str | None,
    undo_of: str | None = None,
) -> None:
    before = sequence.revision
    after = before + 1
    sequence.revision = after
    db.add(
        SequenceOperation(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision_before=before,
            revision_after=after,
            kind=kind,
            payload=payload,
            actor_id=actor_id,
            undo_of=undo_of,
        )
    )
    db.add(
        SequenceRevision(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision=after,
            summary=summary,
        )
    )
