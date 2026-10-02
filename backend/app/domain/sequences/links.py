"""链接片段:同一个链接组(Clip.link_group)里的片段一起移动、修剪、切分、删除、变速。

典型的一组是一段视频和从它分离出去的音频:分开放在两条轨上,却是同一段素材的画和声。只动其中一段,
音画就错开了 —— 而错开几帧是看不出来、听得出来的那种错。

编辑默认作用于整组;每个编辑都带一个 `linked` 开关,False = 这一下只动点中的那段(前端的「临时解链」,
像 Premiere 按住 Alt)。**锁定轨上的组员不跟着动**:锁定的意思就是这条轨上的东西不许被改。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.model_base import new_id
from app.db.models import Clip, Track


def new_link_group() -> str:
    return new_id()


def linked_members(db: Session, clips: Iterable[Clip], *, linked: bool = True) -> list[Clip]:
    """这几段之外、和它们同组的片段(锁定轨上的除外)。`linked=False` 时一个都没有。"""
    clips = list(clips)
    if not linked or not clips:
        return []
    groups = {clip.link_group for clip in clips if clip.link_group}
    if not groups:
        return []
    picked = {clip.id for clip in clips}
    members = db.scalars(
        select(Clip)
        .join(Track, Track.id == Clip.track_id)
        .where(Clip.sequence_id == clips[0].sequence_id, Clip.link_group.in_(groups), Track.locked.is_(False))
        .order_by(Clip.timeline_start)
    )
    return [member for member in members if member.id not in picked]


def with_links(db: Session, clips: Iterable[Clip], *, linked: bool = True) -> list[Clip]:
    """这几段,加上和它们同组的片段。"""
    clips = list(clips)
    return clips + linked_members(db, clips, linked=linked)
