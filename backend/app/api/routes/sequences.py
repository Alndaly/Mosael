from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.api.schemas import InsertClipRequest, SequenceCreate, SequenceOut
from app.db.models import Project, Sequence, Track
from app.domain.sequences.operations import InsertClip, SequenceDomainError, insert_clip as insert_clip_operation

router = APIRouter(tags=["sequences"])


@router.post("/sequences", response_model=SequenceOut)
def create_sequence(body: SequenceCreate, db: DbSession) -> Sequence:
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
def get_sequence(sequence_id: str, db: DbSession) -> Sequence:
    return _get_sequence(db, sequence_id)


@router.get("/projects/{project_id}/sequences", response_model=list[SequenceOut])
def list_sequences(project_id: str, db: DbSession) -> list[Sequence]:
    stmt = (
        select(Sequence)
        .where(Sequence.project_id == project_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
        .order_by(Sequence.updated_at.desc())
    )
    return list(db.scalars(stmt))


@router.post("/sequences/{sequence_id}/clips", response_model=SequenceOut)
def insert_clip(sequence_id: str, body: InsertClipRequest, db: DbSession) -> Sequence:
    try:
        insert_clip_operation(db, sequence_id, InsertClip(**body.model_dump()))
    except SequenceDomainError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    return _get_sequence(db, sequence_id)


def _get_sequence(db, sequence_id: str) -> Sequence:
    stmt = (
        select(Sequence)
        .where(Sequence.id == sequence_id)
        .options(selectinload(Sequence.tracks).selectinload(Track.clips))
    )
    sequence = db.scalar(stmt)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Sequence not found")
    return sequence
