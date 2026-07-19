from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Project, Sequence, Track, Workspace
from app.domain.sequences.history import undo
from app.domain.sequences.operations import (
    DetachClipAudio,
    SetClipGain,
    SetClipTransform,
    clean_transform,
    detach_clip_audio,
    set_clip_gain,
    set_clip_transform,
)
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


def test_set_clip_gain_mute_and_undo() -> None:
    fresh_client()
    with SessionLocal() as db:
        seq, clip = _seq_with_clip(db)
        assert clip.gain == 1.0 and clip.muted is False
        set_clip_gain(db, seq.id, SetClipGain(clip_id=clip.id, gain=0.4, muted=True))
        db.refresh(clip)
        assert clip.gain == 0.4 and clip.muted is True
        set_clip_gain(db, seq.id, SetClipGain(clip_id=clip.id, gain=99, muted=False))  # clamps to 4
        db.refresh(clip)
        assert clip.gain == 4.0 and clip.muted is False
        undo(db, seq.id)
        db.refresh(clip)
        assert clip.gain == 0.4 and clip.muted is True  # back to the prior state


def test_detach_clip_audio_and_undo() -> None:
    fresh_client()
    with SessionLocal() as db:
        seq, clip = _seq_with_clip(db)
        asset = Asset(workspace_id=seq.workspace_id, kind="video", name="v", file_key="media/v.mp4")
        db.add(asset)
        db.flush()
        clip.asset_id = asset.id
        clip.gain = 0.6
        db.commit()

        detach_clip_audio(db, seq.id, DetachClipAudio(clip_id=clip.id))
        db.refresh(seq)
        db.refresh(clip)
        audio_tracks = [t for t in seq.tracks if t.kind == "audio"]
        assert len(audio_tracks) == 1  # created since none existed
        detached = audio_tracks[0].clips[0]
        assert detached.asset_id == asset.id and detached.gain == 0.6  # inherits the clip's gain
        assert clip.muted is True  # video clip muted so audio isn't doubled

        undo(db, seq.id)
        db.refresh(seq)
        db.refresh(clip)
        assert [t for t in seq.tracks if t.kind == "audio"] == []  # created track removed
        assert clip.muted is False  # unmuted
