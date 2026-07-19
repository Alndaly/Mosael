from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AddTrackRequest,
    CutClipRangeRequest,
    CutClipRangesRequest,
    InsertClipRequest,
    InsertTextClipRequest,
    JobOut,
    MoveClipRequest,
    SequenceCreate,
    SequenceOut,
    SetClipEffectsRequest,
    SetClipGainRequest,
    SetClipSpeedRequest,
    SetClipTransformRequest,
    SetSequenceReframeRequest,
    SetClipTextRequest,
    SetSubtitleStyleRequest,
    SetTrackStateRequest,
    GenerateSubtitlesRequest,
    MoveTrackRequest,
    SplitClipPointsRequest,
    SplitClipRequest,
    TrimClipRequest,
)
from app.db.models import Job, Project, Sequence, Track
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm, require_sequence_access
from app.domain.render import start_export
from app.domain.sequences.history import can_redo, can_undo, redo as redo_operation, undo as undo_operation
from app.media.render_plan import RenderPlanError
from app.domain.sequences.operations import (
    AddTrack,
    CutClipRange,
    CutClipRanges,
    DeleteClip,
    InsertClip,
    GenerateSubtitles,
    InsertTextClip,
    MoveClip,
    MoveTrack,
    RemoveTrack,
    RippleDeleteClip,
    SequenceDomainError,
    SetClipEffects,
    SetClipGain,
    SetClipSpeed,
    SetClipTransform,
    SetSequenceReframe,
    SetClipText,
    SetSubtitleStyle,
    SetTrackState,
    SplitClip,
    SplitClipPoints,
    TrimClip,
    add_track as add_track_operation,
    cut_clip_range as cut_clip_range_operation,
    cut_clip_ranges as cut_clip_ranges_operation,
    delete_clip as delete_clip_operation,
    remove_track as remove_track_operation,
    ripple_delete_clip as ripple_delete_clip_operation,
    set_clip_effects as set_clip_effects_operation,
    set_clip_gain as set_clip_gain_operation,
    set_clip_speed as set_clip_speed_operation,
    set_clip_transform as set_clip_transform_operation,
    set_sequence_reframe as set_sequence_reframe_operation,
    set_subtitle_style as set_subtitle_style_operation,
    set_track_state as set_track_state_operation,
    split_clip as split_clip_operation,
    split_clip_at_points as split_clip_points_operation,
    insert_clip as insert_clip_operation,
    generate_subtitles as generate_subtitles_operation,
    insert_text_clip as insert_text_clip_operation,
    set_clip_text as set_clip_text_operation,
    move_clip as move_clip_operation,
    move_track as move_track_operation,
    trim_clip as trim_clip_operation,
)

router = APIRouter(tags=["sequences"])


@router.post("/sequences", response_model=SequenceOut)
def create_sequence(body: SequenceCreate, db: DbSession, user: CurrentUser) -> Sequence:
    ensure_workspace_access(db, user, body.workspace_id)
    sequence = Sequence(**body.model_dump())
    video = Track(sequence=sequence, kind="video", name="V1", position=0)
    audio = Track(sequence=sequence, kind="audio", name="A1", position=1)
    db.add_all([sequence, video, audio])
    project = db.get(Project, body.project_id)
    if project and project.active_sequence_id is None:
        project.active_sequence_id = sequence.id
    db.commit()
    return _get_sequence(db, sequence.id)


@router.get("/sequences/{sequence_id}", response_model=SequenceOut)
def get_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    return _get_sequence(db, sequence_id)


@router.get("/projects/{project_id}/sequences", response_model=list[SequenceOut])
def list_sequences(project_id: str, db: DbSession, user: CurrentUser) -> list[Sequence]:
    project = db.get(Project, project_id)
    if project is not None:
        ensure_workspace_access(db, user, project.workspace_id)
    stmt = (
        select(Sequence)
        .where(Sequence.project_id == project_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
        .order_by(Sequence.updated_at.desc())
    )
    sequences = list(db.scalars(stmt))
    for sequence in sequences:
        sequence.can_undo = can_undo(db, sequence.id)
        sequence.can_redo = can_redo(db, sequence.id)
    return sequences


@router.post("/sequences/{sequence_id}/clips", response_model=SequenceOut)
def insert_clip(sequence_id: str, body: InsertClipRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: insert_clip_operation(db, sequence_id, InsertClip(**body.model_dump())))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/move", response_model=SequenceOut)
def move_clip(sequence_id: str, clip_id: str, body: MoveClipRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: move_clip_operation(db, sequence_id, MoveClip(clip_id=clip_id, **body.model_dump())))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/trim", response_model=SequenceOut)
def trim_clip(sequence_id: str, clip_id: str, body: TrimClipRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: trim_clip_operation(db, sequence_id, TrimClip(clip_id=clip_id, **body.model_dump())))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/clips/{clip_id}/cut-range", response_model=SequenceOut)
def cut_clip_range(sequence_id: str, clip_id: str, body: CutClipRangeRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: cut_clip_range_operation(db, sequence_id, CutClipRange(clip_id=clip_id, **body.model_dump())))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/clips/{clip_id}/cut-ranges", response_model=SequenceOut)
def cut_clip_ranges(
    sequence_id: str, clip_id: str, body: CutClipRangesRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    ranges = tuple((item.src_start, item.src_end) for item in body.ranges)
    _apply(lambda: cut_clip_ranges_operation(db, sequence_id, CutClipRanges(clip_id=clip_id, ranges=ranges)))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/clips/{clip_id}/split", response_model=SequenceOut)
def split_clip(sequence_id: str, clip_id: str, body: SplitClipRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: split_clip_operation(db, sequence_id, SplitClip(clip_id=clip_id, src_time=body.src_time)))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/clips/{clip_id}/split-points", response_model=SequenceOut)
def split_clip_points(
    sequence_id: str, clip_id: str, body: SplitClipPointsRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    """Split one clip into pieces at several source-time cut points (transcript 按句切分)."""
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: split_clip_points_operation(db, sequence_id, SplitClipPoints(clip_id=clip_id, src_times=tuple(body.src_times))))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/tracks/{track_id}", response_model=SequenceOut)
def set_track_state(
    sequence_id: str, track_id: str, body: SetTrackStateRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: set_track_state_operation(db, sequence_id, SetTrackState(track_id=track_id, **body.model_dump())))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/tracks/{track_id}/move", response_model=SequenceOut)
def move_track(sequence_id: str, track_id: str, body: MoveTrackRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: move_track_operation(db, sequence_id, MoveTrack(track_id=track_id, direction=body.direction)))
    return _get_sequence(db, sequence_id)


@router.put("/sequences/{sequence_id}/subtitle-style", response_model=SequenceOut)
def set_subtitle_style(sequence_id: str, body: SetSubtitleStyleRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: set_subtitle_style_operation(db, sequence_id, SetSubtitleStyle(style=body.style)))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/subtitles/generate", response_model=SequenceOut)
def generate_subtitles(sequence_id: str, body: GenerateSubtitlesRequest, db: DbSession, user: CurrentUser) -> Sequence:
    """一键从逐字稿生成字幕:批量把句子插成字幕轨上的文本片段。"""
    require_sequence_access(db, user, sequence_id)
    cues = tuple((cue.text, cue.timeline_start, cue.duration) for cue in body.cues)
    _apply(lambda: generate_subtitles_operation(db, sequence_id, GenerateSubtitles(track_id=body.track_id, cues=cues)))
    return _get_sequence(db, sequence_id)


@router.delete("/sequences/{sequence_id}/clips/{clip_id}", response_model=SequenceOut)
def delete_clip(sequence_id: str, clip_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: delete_clip_operation(db, sequence_id, DeleteClip(clip_id=clip_id)))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/text-clips", response_model=SequenceOut)
def insert_text_clip(sequence_id: str, body: InsertTextClipRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: insert_text_clip_operation(db, sequence_id, InsertTextClip(**body.model_dump())))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/text", response_model=SequenceOut)
def set_clip_text(
    sequence_id: str, clip_id: str, body: SetClipTextRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: set_clip_text_operation(db, sequence_id, SetClipText(clip_id=clip_id, text=body.text)))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/speed", response_model=SequenceOut)
def set_clip_speed(
    sequence_id: str, clip_id: str, body: SetClipSpeedRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: set_clip_speed_operation(db, sequence_id, SetClipSpeed(clip_id=clip_id, speed=body.speed)))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/gain", response_model=SequenceOut)
def set_clip_gain(
    sequence_id: str, clip_id: str, body: SetClipGainRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(
        lambda: set_clip_gain_operation(
            db, sequence_id, SetClipGain(clip_id=clip_id, gain=body.gain, muted=body.muted)
        )
    )
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/transform", response_model=SequenceOut)
def set_clip_transform(
    sequence_id: str, clip_id: str, body: SetClipTransformRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(
        lambda: set_clip_transform_operation(
            db, sequence_id, SetClipTransform(clip_id=clip_id, transform=body.transform)
        )
    )
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/reframe", response_model=SequenceOut)
def set_sequence_reframe(
    sequence_id: str, body: SetSequenceReframeRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(
        lambda: set_sequence_reframe_operation(
            db, sequence_id, SetSequenceReframe(width=body.width, height=body.height, fill_mode=body.fill_mode)
        )
    )
    return _get_sequence(db, sequence_id)


@router.delete("/sequences/{sequence_id}/clips/{clip_id}/ripple", response_model=SequenceOut)
def ripple_delete_clip(sequence_id: str, clip_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: ripple_delete_clip_operation(db, sequence_id, RippleDeleteClip(clip_id=clip_id)))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/tracks", response_model=SequenceOut)
def add_track(sequence_id: str, body: AddTrackRequest, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: add_track_operation(db, sequence_id, AddTrack(kind=body.kind)))
    return _get_sequence(db, sequence_id)


@router.delete("/sequences/{sequence_id}/tracks/{track_id}", response_model=SequenceOut)
def remove_track(sequence_id: str, track_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: remove_track_operation(db, sequence_id, RemoveTrack(track_id=track_id)))
    return _get_sequence(db, sequence_id)


@router.patch("/sequences/{sequence_id}/clips/{clip_id}/effects", response_model=SequenceOut)
def set_clip_effects(
    sequence_id: str, clip_id: str, body: SetClipEffectsRequest, db: DbSession, user: CurrentUser
) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: set_clip_effects_operation(db, sequence_id, SetClipEffects(clip_id=clip_id, effects=body.effects)))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/undo", response_model=SequenceOut)
def undo_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: undo_operation(db, sequence_id))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/redo", response_model=SequenceOut)
def redo_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: redo_operation(db, sequence_id))
    return _get_sequence(db, sequence_id)


@router.post("/sequences/{sequence_id}/export", response_model=JobOut)
def export_sequence(sequence_id: str, db: DbSession, user: CurrentUser) -> Job:
    sequence = require_sequence_access(db, user, sequence_id)
    ensure_workspace_perm(db, user, sequence.workspace_id, "export")
    try:
        return start_export(db, sequence_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RenderPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _apply(operation) -> None:
    try:
        operation()
    except SequenceDomainError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc


def _get_sequence(db, sequence_id: str) -> Sequence:
    stmt = (
        select(Sequence)
        .where(Sequence.id == sequence_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
    )
    sequence = db.scalar(stmt)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    sequence.can_undo = can_undo(db, sequence_id)
    sequence.can_redo = can_redo(db, sequence_id)
    return sequence
