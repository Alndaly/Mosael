"""把一份素材接到一条时间线的轨道末尾。

两个入口共用:工作流的「接到时间线」(executors/subjobs.timeline_append)和画板时间线格的连线(ADR 0030:把一格
视频 / 图片 / 音频连进时间线格,就是把它接到末尾)。「进哪条轨」「轨道到哪儿为止」「这份素材在时间线上多长」只在这里
算一次 —— 两个入口各算一份的话,图片的定格时长迟早一个 5 秒、一个 3 秒。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, object_session

from app.db.models import Asset, Clip, Sequence, Track
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound

#: 图片在时间线上的定格时长(秒)。图片没有 duration,不给就是一段长度为 0 的空片段。
STILL_SECONDS = 5.0

#: 素材种类 → 该进哪种轨道。没列的(图片)按视频走 —— 图片在时间线上就是一段定格视频。
TRACK_FOR_ASSET = {"audio": "audio"}


def track_for_asset(sequence: Sequence, asset_kind: str) -> Track | None:
    """这种素材默认进哪条轨:第一条同类轨道(绝大多数时间线只有一条视频轨和一条音频轨)。"""
    want = TRACK_FOR_ASSET.get(asset_kind, "video")
    return next((one for one in sorted(sequence.tracks or [], key=lambda item: item.position) if one.kind == want), None)


def track_end(track: Track) -> float:
    """这条轨道上最后一段的终点;空轨道是 0。

    查库,不读 `track.clips`:同一个会话里连着接两段时,关系集合还是接第一段之前的样子,第二段就会
    算出「末尾是 0」而落在第一段上 —— 落点上已有片段是覆盖,第一段就没了。
    """
    from app.domain.sequences.coverage import clip_end, clips_on_track

    return max((clip_end(clip) for clip in clips_on_track(object_session(track), track.id)), default=0.0)


def asset_span(asset: Asset) -> float:
    """整段素材在时间线上多长:有时长用时长(在 media_info 里,不是独立列),图片按定格时长,别的是 0。"""
    probed = (asset.media_info or {}).get("duration")
    if probed:
        return float(probed)
    return STILL_SECONDS if asset.kind == "image" else 0.0


def append_asset(db: Session, sequence_id: str, asset_id: str, *, actor_id: str | None = None) -> Clip:
    """把整段素材接到它那种轨道的末尾,交回接上去的那一段。

    **时间线还空着时,画幅跟着第一段走**(ADR 0030 §5):画板上新放的时间线格是默认的横屏,而拼的常常是竖屏的生成视频 ——
    让人先去改画幅再拼,是一步没人记得的仪式。
    """
    from app.domain.sequences.operations import InsertClip, SetSequenceReframe, insert_clip, set_sequence_reframe

    sequence = db.get(Sequence, sequence_id)
    asset = db.get(Asset, asset_id)
    if sequence is None:
        raise SequenceNotFound("seqErr_sequenceNotFound")
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceDomainError("seqErr_assetNotInWorkspace")
    track = track_for_asset(sequence, asset.kind)
    if track is None:
        raise SequenceDomainError("seqErr_noTrackForAsset", kind=asset.kind)
    span = asset_span(asset)
    if span <= 0:
        raise SequenceDomainError("seqErr_assetHasNoLength")
    empty = not any(track.clips for track in sequence.tracks or [])
    info: dict[str, Any] = asset.media_info or {}
    if empty and asset.kind in ("video", "image") and info.get("width") and info.get("height"):
        set_sequence_reframe(db, sequence.id, SetSequenceReframe(width=int(info["width"]), height=int(info["height"]),
                                                                 actor_id=actor_id))
    clip = insert_clip(db, sequence.id, InsertClip(track_id=track.id, asset_id=asset.id, timeline_start=track_end(track),
                                                   src_in=0.0, src_out=span, actor_id=actor_id))
    return clip
