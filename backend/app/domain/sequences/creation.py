"""Creation services owned by the sequence domain."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Project, Sequence, Track


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
