"""The serialised-sequence cache is keyed on revision. These tests guard that key.

The cache is only sound because nothing observable in a SequenceOut can change without the
revision changing too. If some future mutation path forgets to record an operation, the editor
would silently keep rendering stale data — so pin the invariant rather than trusting it."""

from __future__ import annotations

from app.api.routes import sequences as routes
from tests.util import fresh_client


def _setup(client) -> tuple[str, str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    seq = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    track = client.post(f"/api/sequences/{seq['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in track["tracks"] if t["kind"] == "subtitle")
    return project["id"], seq["id"], track_id


def test_edits_are_visible_through_the_cache() -> None:
    client = fresh_client()
    project_id, seq_id, track_id = _setup(client)
    listing = f"/api/projects/{project_id}/sequences"

    client.post(
        f"/api/sequences/{seq_id}/text-clips",
        json={"track_id": track_id, "text": "before", "timeline_start": 0.0, "duration": 2.0},
    )
    first = client.get(listing).json()
    assert _texts(first) == ["before"]
    # A second read must be served from cache and still be identical.
    assert client.get(listing).json() == first

    clip_id = _clips(first)[0]["id"]
    client.patch(f"/api/sequences/{seq_id}/clips/{clip_id}/text", json={"text": "after"})
    assert _texts(client.get(listing).json()) == ["after"], "cache served a stale sequence"


def test_undo_and_redo_invalidate_the_cache() -> None:
    """The subtlest case: undo changes can_undo/can_redo, which are part of the payload but not
    part of any clip. It is only safe because undo records an operation of its own."""
    client = fresh_client()
    project_id, seq_id, track_id = _setup(client)
    listing = f"/api/projects/{project_id}/sequences"

    client.post(
        f"/api/sequences/{seq_id}/text-clips",
        json={"track_id": track_id, "text": "one", "timeline_start": 0.0, "duration": 2.0},
    )
    before = client.get(listing).json()[0]
    assert before["can_undo"] is True and before["can_redo"] is False

    client.post(f"/api/sequences/{seq_id}/undo")
    after_undo = client.get(listing).json()[0]
    assert after_undo["can_redo"] is True, "can_redo was stale after undo"
    assert _texts([after_undo]) == []

    client.post(f"/api/sequences/{seq_id}/redo")
    after_redo = client.get(listing).json()[0]
    assert _texts([after_redo]) == ["one"]
    assert after_redo["can_redo"] is False


def test_a_revision_bump_always_replaces_the_cached_body() -> None:
    client = fresh_client()
    project_id, seq_id, track_id = _setup(client)
    client.post(
        f"/api/sequences/{seq_id}/text-clips",
        json={"track_id": track_id, "text": "x", "timeline_start": 0.0, "duration": 2.0},
    )
    client.get(f"/api/projects/{project_id}/sequences")
    cached_revision, _ = routes._SEQUENCE_JSON[seq_id]

    client.post(f"/api/sequences/{seq_id}/tracks", json={"kind": "audio"})
    client.get(f"/api/projects/{project_id}/sequences")
    new_revision, body = routes._SEQUENCE_JSON[seq_id]
    assert new_revision > cached_revision
    assert '"kind":"audio"' in body.replace(" ", "")


def _clips(sequences: list[dict]) -> list[dict]:
    return [c for s in sequences for t in s["tracks"] for c in (t["clips"] or [])]


def _texts(sequences: list[dict]) -> list[str]:
    return [c["text_override"] for c in _clips(sequences) if c["text_override"]]
