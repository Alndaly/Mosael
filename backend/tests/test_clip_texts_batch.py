"""Batch retext — the operation behind translate-whole-track.

Translating clip-by-clip meant N requests, N revisions and N undo steps, and a failure partway
through left the track half in each language. These tests pin the properties that fixed it:
one revision, all-or-nothing, and one undo."""

from __future__ import annotations

from tests.util import fresh_client


def _sequence_with_subtitles(client, count: int = 3) -> tuple[str, list[str]]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    track = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in track["tracks"] if t["kind"] == "subtitle")

    clip_ids: list[str] = []
    for i in range(count):
        updated = client.post(
            f"/api/sequences/{sequence['id']}/text-clips",
            json={"track_id": track_id, "text": f"原文 {i}", "timeline_start": i * 3.0, "duration": 2.0},
        ).json()
        clips = next(t["clips"] for t in updated["tracks"] if t["id"] == track_id)
        clip_ids = [c["id"] for c in sorted(clips, key=lambda c: c["timeline_start"])]
    return sequence["id"], clip_ids


def test_batch_retext_is_one_revision_and_one_undo() -> None:
    client = fresh_client()
    seq_id, clip_ids = _sequence_with_subtitles(client)
    before = client.get(f"/api/sequences/{seq_id}").json()["revision"]

    res = client.patch(
        f"/api/sequences/{seq_id}/clips/texts",
        json={"texts": [{"clip_id": cid, "text": f"Translated {i}"} for i, cid in enumerate(clip_ids)]},
    )
    assert res.status_code == 200, res.text
    after = res.json()
    assert after["revision"] == before + 1, "three cues must cost one revision, not three"

    texts = _subtitle_texts(after)
    assert texts == ["Translated 0", "Translated 1", "Translated 2"]

    # A single undo puts the whole translation back — previously this took one undo per cue.
    undone = client.post(f"/api/sequences/{seq_id}/undo").json()
    assert _subtitle_texts(undone) == ["原文 0", "原文 1", "原文 2"]

    redone = client.post(f"/api/sequences/{seq_id}/redo").json()
    assert _subtitle_texts(redone) == ["Translated 0", "Translated 1", "Translated 2"]


def test_a_bad_clip_id_writes_nothing() -> None:
    client = fresh_client()
    seq_id, clip_ids = _sequence_with_subtitles(client)

    res = client.patch(
        f"/api/sequences/{seq_id}/clips/texts",
        json={
            "texts": [
                {"clip_id": clip_ids[0], "text": "Translated 0"},
                {"clip_id": "does-not-exist", "text": "Translated 1"},
            ]
        },
    )
    assert res.status_code in (404, 422)

    # The valid entry preceding the bad one must NOT have landed: a partial write is exactly
    # the half-translated track this operation exists to prevent.
    current = client.get(f"/api/sequences/{seq_id}").json()
    assert _subtitle_texts(current) == ["原文 0", "原文 1", "原文 2"]


def test_bilingual_newline_survives_to_ass_as_a_line_break() -> None:
    from app.media.render_executor import _ass_text

    # Bilingual stores "original\ntranslation". A literal newline inside a Dialogue: line would
    # corrupt the ASS file, so it has to become the \N escape.
    rendered = _ass_text("原文\nTranslation")
    assert rendered == "原文\\NTranslation"
    assert "\n" not in rendered


def _subtitle_texts(sequence: dict) -> list[str]:
    clips = [c for t in sequence["tracks"] if t["kind"] == "subtitle" for c in (t["clips"] or [])]
    return [c["text_override"] for c in sorted(clips, key=lambda c: c["timeline_start"])]
