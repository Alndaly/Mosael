"""Removing a track that still holds clips destroys footage, so it takes an explicit yes.

The refusal used to be absolute, which made a populated track undeletable — you had to empty it
by hand first. Now it is refused by default and allowed on confirmation, and because the clips
go with it, undo has to bring all of them back or the removal is a one-way data loss.
"""

from __future__ import annotations

from tests.util import fresh_client


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    track = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in track["tracks"] if t["kind"] == "subtitle")
    for i in range(3):
        client.post(
            f"/api/sequences/{sequence['id']}/text-clips",
            json={"track_id": track_id, "text": f"cue {i}", "timeline_start": i * 3.0, "duration": 2.0},
        )
    return client, sequence["id"], track_id


def _track(client, seq_id: str, track_id: str) -> dict | None:
    sequence = client.get(f"/api/sequences/{seq_id}").json()
    return next((t for t in sequence["tracks"] if t["id"] == track_id), None)


def test_a_populated_track_is_refused_without_confirmation() -> None:
    client, seq, track_id = _setup()
    res = client.delete(f"/api/sequences/{seq}/tracks/{track_id}")
    assert res.status_code == 422
    assert _track(client, seq, track_id) is not None, "the refusal must not have deleted anything"


def test_confirming_removes_the_track_and_its_clips() -> None:
    client, seq, track_id = _setup()
    res = client.delete(f"/api/sequences/{seq}/tracks/{track_id}", params={"with_clips": True})
    assert res.status_code == 200, res.text
    assert _track(client, seq, track_id) is None


def test_undo_brings_back_the_track_and_every_clip_on_it() -> None:
    client, seq, track_id = _setup()
    before = _track(client, seq, track_id)
    texts_before = sorted(c["text_override"] for c in before["clips"])

    client.delete(f"/api/sequences/{seq}/tracks/{track_id}", params={"with_clips": True})
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200

    after = _track(client, seq, track_id)
    assert after is not None, "undo did not restore the track"
    assert sorted(c["text_override"] for c in after["clips"]) == texts_before
    assert after["kind"] == before["kind"] and after["position"] == before["position"]


def test_redo_removes_it_again_instead_of_getting_stuck() -> None:
    client, seq, track_id = _setup()
    client.delete(f"/api/sequences/{seq}/tracks/{track_id}", params={"with_clips": True})
    client.post(f"/api/sequences/{seq}/undo")

    res = client.post(f"/api/sequences/{seq}/redo")
    assert res.status_code == 200, res.text
    assert _track(client, seq, track_id) is None


def test_track_state_survives_the_round_trip() -> None:
    client, seq, track_id = _setup()
    # 字幕轨不显示用的是 hidden(它没有声音,不收 muted)。
    client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json={"hidden": True, "locked": True})

    client.delete(f"/api/sequences/{seq}/tracks/{track_id}", params={"with_clips": True})
    client.post(f"/api/sequences/{seq}/undo")

    restored = _track(client, seq, track_id)
    assert restored["hidden"] is True and restored["locked"] is True


def test_an_empty_track_still_needs_no_confirmation() -> None:
    client, seq, _ = _setup()
    empty = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"}).json()
    empty_id = [t for t in empty["tracks"] if t["kind"] == "audio"][-1]["id"]
    assert client.delete(f"/api/sequences/{seq}/tracks/{empty_id}").status_code == 200


def test_撤销删掉的配音轨_还回来的仍是配音轨() -> None:
    """记录里此前没有 role:撤销删掉的配音轨,还回来的是一条普通轨,再配一次就另开一条新轨。"""
    from app.core.db import SessionLocal
    from app.db.models import Track

    client, seq, _ = _setup()
    with SessionLocal() as db:
        dub = Track(sequence_id=seq, kind="audio", name="配音", position=9, role="dub")
        db.add(dub)
        db.commit()
        dub_id = dub.id
    assert client.delete(f"/api/sequences/{seq}/tracks/{dub_id}").status_code == 200
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200
    assert _track(client, seq, dub_id)["role"] == "dub"


def test_迁移补齐老的删轨记录_撤销照样走得通() -> None:
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.db.migrations import _migrate_removed_track_records_are_complete, migration_plan
    from app.db.models import SequenceOperation

    assert "migrate-removed-track-records-are-complete" in {s.name for s in migration_plan().steps}
    client, seq, track_id = _setup()
    client.delete(f"/api/sequences/{seq}/tracks/{track_id}", params={"with_clips": True})
    with SessionLocal() as db:
        operation = db.scalars(
            select(SequenceOperation).where(SequenceOperation.sequence_id == seq, SequenceOperation.kind == "remove_track")
        ).one()
        old_shape = ("muted", "solo", "locked", "duck", "role")
        operation.payload = {k: v for k, v in operation.payload.items() if k not in old_shape}
        db.commit()
    _migrate_removed_track_records_are_complete()
    _migrate_removed_track_records_are_complete()
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200
    restored = _track(client, seq, track_id)
    assert restored["role"] == "" and len(restored["clips"]) == 3
