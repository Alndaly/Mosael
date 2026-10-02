"""Creation services owned by the sequence domain."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Clip, Project, Sequence, Track
from app.domain.sequences._timeline import RESTORABLE_CLIP_FIELDS


@dataclass(frozen=True)
class SequenceScaffold:
    """A new sequence and its minimum editable audio/video track pair."""

    sequence: Sequence
    video_track: Track
    audio_track: Track


def create_sequence_scaffold(
    db: Session,
    project: Project,
    *,
    name: str,
    width: int,
    height: int,
    fps: float,
) -> SequenceScaffold:
    """Stage a ready-to-edit sequence for ``project`` in the caller's transaction.

    The sequence domain owns creation of Sequence and Track rows.  The caller
    keeps transaction ownership so a project plus its initial timeline either
    commits as one unit or not at all.
    """
    sequence = Sequence(
        workspace_id=project.workspace_id,
        project=project,
        name=name,
        width=width,
        height=height,
        fps=fps,
    )
    video = Track(sequence=sequence, kind="video", name="V1", position=0)
    audio = Track(sequence=sequence, kind="audio", name="A1", position=1)
    db.add_all([sequence, video, audio])
    db.flush()
    return SequenceScaffold(sequence=sequence, video_track=video, audio_track=audio)


def copy_sequence(db: Session, source: Sequence, project: Project, *, name: str) -> Sequence:
    """把 ``source`` 复制成 ``project`` 里的一条新时间线:画幅、改画幅、字幕样式、每条轨和轨上的每一段。

    编辑历史(操作、撤销、修订)不带过去 —— 副本从这一刻开始自己的历史;素材是引用,不复制文件。
    在调用方的事务里 flush,不提交。
    """
    copy = Sequence(
        workspace_id=project.workspace_id,
        project=project,
        name=name,
        width=source.width,
        height=source.height,
        fps=source.fps,
        reframe=dict(source.reframe or {}),
        subtitle_style=dict(source.subtitle_style or {}),
    )
    db.add(copy)
    db.flush()
    for track in source.tracks:
        new_track = Track(
            sequence=copy, kind=track.kind, name=track.name, position=track.position, locked=track.locked,
            muted=track.muted, hidden=track.hidden, solo=track.solo, duck=track.duck, role=track.role,
        )
        db.add(new_track)
        db.flush()
        for clip in track.clips:
            # 位置之外的字段照撤销重建的那张表抄(RESTORABLE_CLIP_FIELDS),不再手写一份 —— 手写的那份
            # 漏掉了后来加的链接组(副本里画和分离出去的声音不再一起动)。链接组号照抄无妨:组员查找
            # 限在同一条序列里(links.linked_members)。深拷贝:JSON 列共享同一个 dict 的话,改副本会改到原片。
            db.add(Clip(
                workspace_id=project.workspace_id, sequence_id=copy.id, track_id=new_track.id,
                asset_id=clip.asset_id, timeline_start=clip.timeline_start, src_in=clip.src_in, src_out=clip.src_out,
                **{field: deepcopy(getattr(clip, field)) for field in RESTORABLE_CLIP_FIELDS},
            ))
    db.flush()
    return copy
