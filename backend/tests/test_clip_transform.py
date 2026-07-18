from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Clip, Project, Sequence, Track, Workspace
from app.domain.sequences.history import undo
from app.domain.sequences.operations import SetClipTransform, clean_transform, set_clip_transform
from tests.util import fresh_client


def _seq_with_clip(db) -> tuple[Sequence, Clip]:
    ws = Workspace(name="W")
    db.add(ws)
    db.flush()
    pr = Project(workspace_id=ws.id, name="P")
    db.add(pr)
    db.flush()
    seq = Sequence(workspace_id=ws.id, project_id=pr.id, name="S")
    tr = Track(sequence=seq, kind="video", name="V1", position=0)
    db.add_all([seq, tr])
    db.flush()
    clip = Clip(workspace_id=ws.id, sequence_id=seq.id, track_id=tr.id, timeline_start=0, src_in=0, src_out=5)
    db.add(clip)
    db.commit()
    return seq, clip


def test_clean_transform_fills_defaults_and_clamps() -> None:
    assert clean_transform({}) == {"scale": 1.0, "x": 0.0, "y": 0.0, "rotation": 0.0, "opacity": 1.0}
    clamped = clean_transform({"scale": 99, "opacity": 5, "rotation": -999})
    assert clamped["scale"] == 4.0 and clamped["opacity"] == 1.0 and clamped["rotation"] == -180.0


def test_set_clip_transform_and_undo() -> None:
    fresh_client()
    with SessionLocal() as db:
        seq, clip = _seq_with_clip(db)
        set_clip_transform(db, seq.id, SetClipTransform(clip_id=clip.id, transform={"scale": 1.5, "rotation": 90}))
        db.refresh(clip)
        assert clip.transform["scale"] == 1.5 and clip.transform["rotation"] == 90.0
        undo(db, seq.id)
        db.refresh(clip)
        assert clip.transform == {}  # 恢复到设置前(恒等)
