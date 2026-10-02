"""片段级「替换媒体」:片段留在原地,换成另一份素材。

位置、时长、入出点、速度、音量、调色、变换、关键帧 —— 一样都不动,只换「放的是哪份素材」。用在:
- 降噪、分离之后的产出直接顶替原来那份(素材本身是同一段内容,时间轴一一对应);
- 同一份素材用在好几处时一次换掉(`clips_using`);
- 脱机片段(素材被删了)重新接上一份。

此前只能删掉再拖一份进来,而那会把这一段上做过的所有调整一起丢掉。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Track
from app.domain.sequences._timeline import _record_operation, _require_clip, _require_sequence
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.sequences.journal import Journal

#: 哪种轨能放哪种素材。和 append.TRACK_FOR_ASSET 的方向相反:这里问的是「这条轨上能不能换成它」。
_ACCEPTS = {"video": ("video", "image"), "audio": ("audio", "video")}
#: 新素材比片段用到的出点短这么一点不算短(探测时长的取整)。
_DURATION_SLACK = 0.05


@dataclass(frozen=True)
class ReplaceClipMedia:
    clip_ids: tuple[str, ...]
    asset_id: str
    actor_id: str | None = None


def clips_using(sequence: Sequence, asset_id: str) -> list[str]:
    """这条时间线上用着这份素材的全部片段(批量替换同一素材时用)。"""
    return [clip.id for track in sequence.tracks or [] for clip in track.clips or [] if clip.asset_id == asset_id]


def replace_clip_media(db: Session, sequence_id: str, op: ReplaceClipMedia) -> Sequence:
    """把这些片段换成 `asset_id` 那份素材。全部先验过再动:一段不合适,一段都不换。"""
    sequence = _require_sequence(db, sequence_id)
    if not op.clip_ids:
        raise SequenceDomainError("No clips to replace")
    asset = db.get(Asset, op.asset_id)
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceNotFound("Asset not found")
    duration = float((asset.media_info or {}).get("duration") or 0.0)
    clips: list[Clip] = []
    for clip_id in dict.fromkeys(op.clip_ids):
        clip = _require_clip(db, sequence_id, clip_id)
        track = db.get(Track, clip.track_id)
        if not (clip.asset_id or clip.offline_asset):
            raise SequenceDomainError("seqErr_replaceTextClip")
        if track is None or asset.kind not in _ACCEPTS.get(track.kind, ()):
            raise SequenceDomainError("seqErr_replaceWrongKind", kind=asset.kind, track=track.kind if track else "")
        # 图片没有时长(定格多久都行);音视频要覆盖得了片段用到的出点,不然那一段放到一半就没了。
        if asset.kind != "image" and duration > 0 and clip.src_out > duration + _DURATION_SLACK:
            raise SequenceDomainError("seqErr_replaceTooShort", needed=f"{clip.src_out:.1f}", has=f"{duration:.1f}")
        clips.append(clip)
    # 经由改动日志改(见 journal.py):撤销 / 重做和别的片段级操作是同一对实现,不另写一份还原。
    journal = Journal(db, sequence)
    for clip in clips:
        journal.update(clip, asset_id=asset.id, offline_asset=None)
    _record_operation(
        db,
        sequence,
        kind="replace_clip_media",
        payload={"asset_id": asset.id, "changes": journal.entries},
        summary={"operation": "replace_clip_media", "count": len(clips), "asset_id": asset.id},
        actor_id=op.actor_id,
    )
    return sequence
