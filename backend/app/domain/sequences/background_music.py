"""给一条时间线铺背景音乐:一首配乐从头铺到现有内容的末尾,垫在旁白底下。

带货口播每一拍的视频是静音的(画外音在说话),成片只剩旁白;真跑时维护者说「背景音乐也没了」。
「铺一条统一配乐」是时间线上的一件事,不是哪个模板的私活 —— 混剪、整片、数字人以后都会要,所以在这里做一次:

- **一条「配乐」轨**(`Track.role == "music"`,和配音轨按用途认、不按名字认同一个理由):再铺一次(重跑、
  从中断处继续)换掉轨上原来那首,不叠第二条;
- **铺满到成片末尾**,不加速 —— 音乐被拉快就变调了(`timeline_append` 的「最长占几秒」是给口播用的,会加速)。
  曲子比成片长就按出点截;**比成片短就首尾接着再铺一遍**,接缝两边各淡一小段(`SEAM_FADE`)。起初是「放完为止、
  不循环」:同一个音乐模型、同一段描述,一次出 20 秒、一次出 6 秒,10 秒的成片后 4 秒就没了配乐,维护者听出来了;
- **垫在下面,按听感定音量**:量这首曲子实际铺上的那一段有多响,把增益定到 `BED_LOUDNESS`;这条轨标「闪避」
  (`duck`)—— 有旁白的地方渲染时再压低 `DUCK_GAIN`(约 10.5 dB)。不乘固定倍数:生成的曲子响度差得很远,
  起初的「× 0.35 再闪避」在一首拆掉人声的伴奏(−22.8 LUFS)上把它压到了旁白底下 22 dB,成片里等于没有;
  开头淡入、结尾淡出,不在成片最后一帧戛然而止。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Sequence, Track
from app.media.loudness import integrated_loudness
from app.media.paths import resolve_key
from app.domain.sequences.append import asset_span, track_end
from app.domain.sequences.clip_properties import SetClipEffects, SetClipGain, set_clip_effects, set_clip_gain
from app.domain.sequences.coverage import clips_on_track
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.fitting import fit_asset_on_track
from app.domain.sequences.placement import DeleteClipsBatch, InsertClip, delete_clips_batch, insert_clip
from app.domain.sequences.tracks import AddTrack, SetTrackState, add_track, set_track_state

#: 配乐轨的用途。
MUSIC_ROLE = "music"
#: 配乐垫底的响度(LUFS,闪避之前)。取 EBU R128 的参考响度 −23:没有旁白的地方略低于人声(TTS 旁白实测
#: 约 −20),有旁白的地方闪避再压约 10.5 dB,落在旁白底下十二三 dB —— 听得见,不抢话。
BED_LOUDNESS = -23.0
#: 量不出响度时(读不了、整段静音)的增益:原样铺,交给闪避去让旁白。
UNMEASURED_GAIN = 1.0
#: 按响度算出来的增益夹在这里面:太轻的曲子不放大到失真,太响的也不压成没有。
GAIN_RANGE = (0.1, 4.0)
DEFAULT_FADE_IN = 0.5
DEFAULT_FADE_OUT = 1.5
#: 曲子不够长、接着再铺一遍时,接缝两边各淡多少秒:短到不像停顿,长到听不出硬切。
SEAM_FADE = 0.25
#: 最后剩下不到这么长就不再起一遍了(起一遍、刚淡入就淡出,听着是一声杂音),上一遍淡出收尾。
MIN_TAIL = 1.0


@dataclass(frozen=True)
class LaidMusic:
    #: 按时间先后:曲子够长就一段,不够长就首尾接着的几段。
    clip_ids: tuple[str, ...]
    track_id: str
    #: 配乐实际铺了几秒(最后剩下不到 `MIN_TAIL` 时会比成片短那么一点)。
    duration: float
    #: 成片现有内容到第几秒(配乐铺到这里为止)。
    content_end: float
    #: 这首配乐用的增益(按响度算出来的,或调用方给的)。
    gain: float


def content_end(sequence: Sequence) -> float:
    """这条时间线现有内容的末尾:画面、旁白、音效的最后一秒。字幕不算(它跟着画面走),配乐轨自己不算。"""
    return max(
        (track_end(track) for track in sequence.tracks or [] if track.kind != "subtitle" and track.role != MUSIC_ROLE),
        default=0.0,
    )


def lay_background_music(
    db: Session,
    sequence: Sequence,
    asset: Asset,
    *,
    gain: float | None = None,
    fade_in: float = DEFAULT_FADE_IN,
    fade_out: float = DEFAULT_FADE_OUT,
    actor_id: str | None,
) -> LaidMusic:
    """把 `asset` 作为配乐从 0 秒铺到现有内容的末尾(见模块说明)。时间线是空的、素材不是音频时拒。

    `gain` 不给就按这首曲子实际铺上那一段的响度定(`bed_gain`);给了就照给的。
    """
    if asset.kind != "audio":
        raise SequenceDomainError("seqErr_musicNotAudio")
    end = content_end(sequence)
    if end <= 0:
        raise SequenceDomainError("seqErr_nothingToScore")
    span = asset_span(asset)
    if span <= 0:
        raise SequenceDomainError("seqErr_musicNotAudio")
    if gain is None:
        gain = bed_gain(integrated_loudness(resolve_key(asset.file_key), seconds=min(span, end)))
    track = _music_track(db, sequence, actor_id)
    passes = _passes(span, end)
    clip_ids: list[str] = []
    for index, (start, length) in enumerate(passes):
        src_out = fit_asset_on_track(asset, track, 0.0, length)
        clip = insert_clip(db, sequence.id, InsertClip(
            track_id=track.id, asset_id=asset.id, timeline_start=start, src_in=0.0, src_out=src_out, actor_id=actor_id,
        ))
        set_clip_gain(db, sequence.id, SetClipGain(clip_id=clip.id, gain=gain, actor_id=actor_id))
        fades = {
            "fade_in": fade_in if index == 0 else SEAM_FADE,
            "fade_out": fade_out if index == len(passes) - 1 else SEAM_FADE,
        }
        set_clip_effects(db, sequence.id, SetClipEffects(
            clip_id=clip.id, effects={**(clip.effects or {}), **fades}, actor_id=actor_id,
        ))
        clip_ids.append(clip.id)
    laid = sum(length for _start, length in passes)
    return LaidMusic(clip_ids=tuple(clip_ids), track_id=track.id, duration=laid, content_end=end, gain=gain)


def _passes(span: float, end: float) -> list[tuple[float, float]]:
    """一首 `span` 秒的曲子铺满 `end` 秒要铺哪几遍:每遍 (从第几秒起, 铺几秒)。最后剩不到 `MIN_TAIL` 的不起。"""
    passes: list[tuple[float, float]] = []
    start = 0.0
    while start < end:
        length = min(span, end - start)
        if passes and length < MIN_TAIL:
            break
        passes.append((start, length))
        start += length
    return passes


def bed_gain(loudness: float | None) -> float:
    """把一首响度为 `loudness`(LUFS)的曲子垫到 `BED_LOUDNESS` 要乘的增益。没量到就原样。"""
    if loudness is None:
        return UNMEASURED_GAIN
    low, high = GAIN_RANGE
    return round(max(low, min(high, 10 ** ((BED_LOUDNESS - loudness) / 20))), 3)


def _music_track(db: Session, sequence: Sequence, actor_id: str | None) -> Track:
    """这条时间线的配乐轨:有就清空它(换掉原来那首),没有就在最下面建一条。都标上闪避。"""
    existing = [one for one in sequence.tracks or [] if one.kind == "audio" and one.role == MUSIC_ROLE]
    if existing:
        track = min(existing, key=lambda one: one.position)
        old = tuple(clip.id for clip in clips_on_track(db, track.id))
        if old:
            delete_clips_batch(db, sequence.id, DeleteClipsBatch(clip_ids=old, linked=False, actor_id=actor_id))
    else:
        before = {one.id for one in db.scalars(select(Track).where(Track.sequence_id == sequence.id))}
        add_track(db, sequence.id, AddTrack(kind="audio", actor_id=actor_id))
        db.flush()
        track = next(one for one in db.scalars(select(Track).where(Track.sequence_id == sequence.id)) if one.id not in before)
        track.role = MUSIC_ROLE
    if not track.duck:
        set_track_state(db, sequence.id, SetTrackState(track_id=track.id, duck=True, actor_id=actor_id))
    return track


__all__ = ["BED_LOUDNESS", "DEFAULT_FADE_IN", "DEFAULT_FADE_OUT", "MIN_TAIL", "MUSIC_ROLE", "SEAM_FADE", "LaidMusic", "bed_gain",
           "content_end", "lay_background_music"]
