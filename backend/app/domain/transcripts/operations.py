from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Asset, Transcript, TranscriptSegment, TranscriptToken

"""
Transcripts are analysis results attached to assets (plan §3.2). They are
never a second edit state: the editor projects them through clip src ranges.
Attaching replaces any prior transcript for the asset.
"""


class TranscriptDomainError(ValueError):
    pass


@dataclass(frozen=True)
class TokenIn:
    start_time: float
    end_time: float
    text: str


@dataclass(frozen=True)
class SegmentIn:
    start_time: float
    end_time: float
    text: str
    speaker: str | None = None
    tokens: tuple[TokenIn, ...] = field(default_factory=tuple)


def attach_transcript(
    db: Session,
    *,
    asset_id: str,
    language: str,
    segments: list[SegmentIn],
    source: str = "imported",
) -> Transcript:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise TranscriptDomainError("Asset not found")
    for segment in segments:
        if segment.end_time <= segment.start_time:
            raise TranscriptDomainError("Segment end_time must be greater than start_time")

    existing = db.scalars(select(Transcript).where(Transcript.asset_id == asset_id))
    for transcript in existing:
        db.delete(transcript)

    transcript = Transcript(
        workspace_id=asset.workspace_id,
        asset_id=asset_id,
        language=language,
        status="ready",
        source=source,
    )
    db.add(transcript)
    for segment_in in sorted(segments, key=lambda item: item.start_time):
        segment = TranscriptSegment(
            transcript=transcript,
            start_time=segment_in.start_time,
            end_time=segment_in.end_time,
            text=segment_in.text,
            speaker=segment_in.speaker,
        )
        db.add(segment)
        for index, token in enumerate(segment_in.tokens):
            db.add(
                TranscriptToken(
                    segment=segment,
                    token_index=index,
                    start_time=token.start_time,
                    end_time=token.end_time,
                    text=token.text,
                )
            )
    db.commit()
    db.refresh(transcript)
    return transcript


def get_transcript_for_asset(db: Session, asset_id: str) -> Transcript | None:
    stmt = (
        select(Transcript)
        .where(Transcript.asset_id == asset_id)
        .options(selectinload(Transcript.segments).selectinload(TranscriptSegment.tokens))
        .order_by(Transcript.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)
