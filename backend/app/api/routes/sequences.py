from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    CutClipRangeRequest,
    InsertClipRequest,
    JobOut,
    MoveClipRequest,
    SequenceCreate,
    SequenceOut,
    TrimClipRequest,
)
from app.db.models import Job, Project, Sequence, Track
from app.core.permissions import ensure_workspace_access, require_sequence_access
from app.domain.render import start_export
from app.domain.sequences.history import can_redo, can_undo, redo as redo_operation, undo as undo_operation
from app.media.render_plan import RenderPlanError
from app.domain.sequences.operations import (
    CutClipRange,
    DeleteClip,
    InsertClip,
    MoveClip,
    SequenceDomainError,
    TrimClip,
    cut_clip_range as cut_clip_range_operation,
    delete_clip as delete_clip_operation,
    insert_clip as insert_clip_operation,
    move_clip as move_clip_operation,
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


@router.delete("/sequences/{sequence_id}/clips/{clip_id}", response_model=SequenceOut)
def delete_clip(sequence_id: str, clip_id: str, db: DbSession, user: CurrentUser) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    _apply(lambda: delete_clip_operation(db, sequence_id, DeleteClip(clip_id=clip_id)))
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
    require_sequence_access(db, user, sequence_id)
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
