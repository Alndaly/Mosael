"""片段与画面属性:变速、音量、分离音频、特效、画面变换与改画幅。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Track
from app.domain.sequences._timeline import (
    _record_operation,
    _require_clip,
    _require_sequence,
    require_speed,
    timeline_span,
)
from app.domain.sequences.coverage import EPS, clip_end, clips_on_track, shift
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.sequences.journal import Journal
from app.domain.sequences.links import new_link_group, with_links
from app.media.render_plan import TRANSFORM_BOUNDS, TRANSFORM_DEFAULTS


@dataclass(frozen=True)
class SetClipEffects:
    clip_id: str
    effects: dict[str, Any]
    actor_id: str | None = None


@dataclass(frozen=True)
class SetClipSpeed:
    clip_id: str
    speed: float
    #: 变速改了片段在时间线上的长度,后面的片段怎么办:
    #:
    #: - True(默认,剪映的习惯):同轨后续片段跟着推开 / 拉回,彼此的间距保留 —— 慢放不会盖住下一段,
    #:   快放也不会在后面留出一截空白;
    #: - False:后面的一段都不动。快放留出空当;慢放到会盖住下一段时**拒绝**,而不是替用户把下一段
    #:   裁掉 —— 改的是这一段的属性,用户没有在「放下」什么,悄悄删掉别人的画面是最难发现的那种错。
    ripple: bool = True
    #: 链接组一起变速(分离出去的音频和画面同速,才对得上);False = 只改这一段。见 links.py。
    linked: bool = True
    actor_id: str | None = None


def set_clip_speed(db: Session, sequence_id: str, op: SetClipSpeed) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    speed = require_speed(op.speed)
    group = with_links(db, [clip], linked=op.linked)
    if not op.ripple:
        # 先全部量过再动手:组里第二段放不下时,第一段不该已经改了速。
        for one in group:
            _ensure_room(db, one, speed)
    journal = Journal(db, sequence)
    for one in group:
        _respeed(journal, one, speed, ripple=op.ripple)
    _record_operation(
        db,
        sequence,
        kind="set_clip_speed",
        payload={"clip_id": clip.id, "speed": speed, "changes": journal.entries},
        summary={"operation": "set_clip_speed", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


def _followers(db: Session, clip: Clip) -> list[Clip]:
    end = clip_end(clip)
    return [other for other in clips_on_track(db, clip.track_id) if other.id != clip.id and other.timeline_start >= end - EPS]


def _ensure_room(db: Session, clip: Clip, speed: float) -> None:
    """不推开后面的时,改速之后放不放得下;放不下就拒绝。"""
    new_end = clip.timeline_start + (clip.src_out - clip.src_in) / speed
    next_start = min((other.timeline_start for other in _followers(db, clip)), default=float("inf"))
    if new_end > next_start + EPS:
        raise SequenceDomainError("seqErr_speedWouldOverlap")


def _respeed(journal: Journal, clip: Clip, speed: float, *, ripple: bool) -> None:
    followers = _followers(journal.db, clip)
    old_end = clip_end(clip)
    journal.update(clip, speed=speed)
    if ripple:
        shift(journal, followers, clip_end(clip) - old_end)


@dataclass(frozen=True)
class SetClipGain:
    clip_id: str
    gain: float
    muted: bool
    actor_id: str | None = None


def set_clip_gain(db: Session, sequence_id: str, op: SetClipGain) -> Sequence:
    """A clip's own audio level/mute (a video clip carries its audio, like PR/DaVinci)."""
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    gain = max(0.0, min(4.0, float(op.gain)))
    previous = {"gain": clip.gain, "muted": clip.muted}
    clip.gain = gain
    clip.muted = bool(op.muted)
    _record_operation(
        db,
        sequence,
        kind="set_clip_gain",
        payload={"clip_id": clip.id, "gain": gain, "muted": bool(op.muted), "previous": previous},
        summary={"operation": "set_clip_gain", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


@dataclass(frozen=True)
class DetachClipAudio:
    clip_id: str
    #: 放到音频轨上的那份声音。缺省是片段自己的素材;译配分离人声时换成它的背景音 ——
    #: 这时源片段也可以在音频轨上(之前已经分离过一次的原声)。
    audio_asset_id: str | None = None
    actor_id: str | None = None


def _range_free(track: Track, start: float, end: float) -> bool:
    for other in track.clips:
        other_end = other.timeline_start + timeline_span(other)
        if start < other_end - 1e-6 and other.timeline_start < end - 1e-6:
            return False
    return True


def detach_clip_audio(db: Session, sequence_id: str, op: DetachClipAudio) -> Sequence:
    """Split a video clip's audio onto an audio track (PR/DaVinci 分离音频): copy the clip's
    audio to the first free audio track (creating one if needed) and mute the source clip so the
    audio isn't doubled. The detached audio inherits the clip's speed/gain.

    With `audio_asset_id` the copy plays *that* asset instead (same timing) — the dub flow puts a
    clip's separated background there. Tracks with a role (the dub track) are never chosen.
    """
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    track = db.get(Track, clip.track_id)
    replacing = bool(op.audio_asset_id)
    if track is None or track.kind not in (("video", "audio") if replacing else ("video",)):
        raise SequenceDomainError("seqErr_detachAudioVideoOnly")
    if not clip.asset_id:
        raise SequenceDomainError("seqErr_clipNoAudioSource")
    audio_asset_id = op.audio_asset_id or clip.asset_id
    if replacing:
        audio_asset = db.get(Asset, audio_asset_id)
        if audio_asset is None or audio_asset.workspace_id != sequence.workspace_id or audio_asset.kind not in ("audio", "video"):
            raise SequenceNotFound("Asset not found")
    duration = timeline_span(clip)
    start, end = clip.timeline_start, clip.timeline_start + duration

    audio_tracks = sorted((t for t in sequence.tracks if t.kind == "audio" and not t.role), key=lambda t: t.position)
    target = next((t for t in audio_tracks if t.id != track.id and _range_free(t, start, end)), None)
    journal = Journal(db, sequence)
    if target is None:
        target = journal.create_track(
            Track(
                sequence_id=sequence.id,
                kind="audio",
                name=f"A{sum(1 for t in sequence.tracks if t.kind == 'audio') + 1}",
                position=max((t.position for t in sequence.tracks), default=-1) + 1,
            )
        )

    # 画和分离出去的声音进同一个链接组:之后移动、修剪、切分、删除默认一起,音画不会被单独拖开。
    # 画面已经在一个组里(之前分离过一次)就加进那一组。
    group = clip.link_group or new_link_group()
    journal.create(
        Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=target.id,
            asset_id=audio_asset_id,
            timeline_start=clip.timeline_start,
            src_in=clip.src_in,
            src_out=clip.src_out,
            speed=clip.speed,
            gain=clip.gain,
            link_group=group,
        )
    )
    journal.update(clip, muted=True, link_group=group)

    _record_operation(
        db,
        sequence,
        kind="detach_clip_audio",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "detach_clip_audio", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
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
    return sequence


def _clean_keyframes(raw: Any) -> list[dict[str, float]]:
    """清洗关键帧轨:每点 t 钳到 [0,1],各属性按 transform 范围钳制,丢弃空点,按 t 升序。

    每个属性独立成轨——一个点只携带它打了的属性,缺的属性从静态基值取。非 dict 的点、t 缺失
    或非数字的点直接剔除;某属性值非数字则跳过该属性。存下来的形态与 render_plan 侧的读取语义
    一致,保证「打了就能导出、导出即所见」。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item["t"])
        except (KeyError, TypeError, ValueError):
            continue
        point: dict[str, float] = {"t": max(0.0, min(1.0, t))}
        for key, (lo, hi) in TRANSFORM_BOUNDS.items():
            if key not in item:
                continue
            try:
                value = float(item[key])
            except (TypeError, ValueError):
                continue
            point[key] = max(lo, min(hi, value))
        if len(point) > 1:  # 除 t 外至少携带一个属性,才是有效关键帧
            cleaned.append(point)
    cleaned.sort(key=lambda p: p["t"])
    return cleaned


def clean_transform(raw: dict[str, Any]) -> dict[str, Any]:
    """归一化片段变换:补默认、转 float、按范围钳制;保留并清洗关键帧轨。"""
    out: dict[str, Any] = {}
    for key, default in TRANSFORM_DEFAULTS.items():
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError) as exc:
            raise SequenceDomainError("seqErr_transformNotNumber", key=key) from exc
        lo, hi = TRANSFORM_BOUNDS[key]
        out[key] = max(lo, min(hi, value))
    keyframes = _clean_keyframes(raw.get("keyframes"))
    if keyframes:
        out["keyframes"] = keyframes
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
        raise SequenceDomainError("seqErr_canvasSizeRange")
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
    return sequence
