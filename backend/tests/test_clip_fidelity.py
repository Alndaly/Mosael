"""Editing a clip must not quietly reset the parts of it you cannot see.

A clip carries more than a position: speed, gain, mute, colour/effects, transform, and for a
subtitle its text. Several operations rebuilt clips from a partial payload, so undoing a delete
or cutting a clip in half returned it at 1x, unity gain, ungraded, and — for subtitles — blank.
The loss is silent and unrecoverable: the previous values exist nowhere else.

The other half is arithmetic. src_out - src_in is a duration in SOURCE time; how long a clip
occupies the TIMELINE is that divided by speed. Three places used the source delta directly, so
anything not at 1x landed in the wrong place and overwrote its neighbour.
"""

from __future__ import annotations

import pytest

from tests.util import fresh_client


@pytest.fixture()
def editor():
    """A sequence with one video track, one subtitle track, and a 10-second asset."""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    video_track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    with_sub = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    sub_track = next(t["id"] for t in with_sub["tracks"] if t["kind"] == "subtitle")

    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": ws,
            "project_id": project["id"],
            "kind": "video",
            "name": "clip.mp4",
            "file_key": "media/clip.mp4",
            "media_info": {"duration": 20},
        },
    )
    assert asset.status_code == 200, asset.text
    asset_id = asset.json()["id"]
    return {
        "client": client,
        "ws": ws,
        "seq": sequence["id"],
        "video_track": video_track,
        "sub_track": sub_track,
        "asset_id": asset_id,
    }


def _clips(client, seq_id: str, track_id: str) -> list[dict]:
    sequence = client.get(f"/api/sequences/{seq_id}").json()
    clips = next(t["clips"] for t in sequence["tracks"] if t["id"] == track_id)
    return sorted(clips, key=lambda c: c["timeline_start"])


def _insert_video(editor, *, start=0.0, src_in=0.0, src_out=10.0) -> str:
    client = editor["client"]
    res = client.post(
        f"/api/sequences/{editor['seq']}/clips",
        json={
            "track_id": editor["video_track"],
            "asset_id": editor["asset_id"],
            "timeline_start": start,
            "src_in": src_in,
            "src_out": src_out,
        },
    )
    assert res.status_code == 200, res.text
    return _clips(client, editor["seq"], editor["video_track"])[-1]["id"]


def _dress(client, seq_id: str, clip_id: str) -> None:
    """Give a clip every non-positional property a user can set."""
    assert client.patch(f"/api/sequences/{seq_id}/clips/{clip_id}/speed", json={"speed": 2.0}).status_code == 200
    assert (
        client.patch(f"/api/sequences/{seq_id}/clips/{clip_id}/gain", json={"gain": 0.3, "muted": True}).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/sequences/{seq_id}/clips/{clip_id}/effects", json={"effects": {"video_fade": 1.5}}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/sequences/{seq_id}/clips/{clip_id}/transform", json={"transform": {"scale": 2.0}}
        ).status_code
        == 200
    )


# --------------------------------------------------------------------------------------
# Fidelity: what a clip is must survive a round trip
# --------------------------------------------------------------------------------------


def test_undoing_a_delete_restores_the_whole_clip_not_just_its_position(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    clip_id = _insert_video(editor)
    _dress(client, seq, clip_id)
    before = _clips(client, seq, editor["video_track"])[0]

    assert client.delete(f"/api/sequences/{seq}/clips/{clip_id}").status_code == 200
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200

    after = _clips(client, seq, editor["video_track"])[0]
    for field in ("speed", "gain", "muted", "effects", "transform", "src_in", "src_out", "timeline_start"):
        assert after[field] == before[field], f"undo lost {field}: {before[field]!r} -> {after[field]!r}"


def test_undoing_a_subtitle_delete_keeps_the_text(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    res = client.post(
        f"/api/sequences/{seq}/text-clips",
        json={"track_id": editor["sub_track"], "text": "那我是不是应该晚一点再说我爱你?", "timeline_start": 0.0, "duration": 2.0},
    )
    assert res.status_code == 200, res.text
    clip_id = _clips(client, seq, editor["sub_track"])[0]["id"]

    assert client.delete(f"/api/sequences/{seq}/clips/{clip_id}").status_code == 200
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200

    restored = _clips(client, seq, editor["sub_track"])[0]
    assert restored["text_override"] == "那我是不是应该晚一点再说我爱你?", "the words are gone from the database"


def test_splitting_a_subtitle_keeps_the_text_on_both_halves(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    client.post(
        f"/api/sequences/{seq}/text-clips",
        json={"track_id": editor["sub_track"], "text": "keep me", "timeline_start": 0.0, "duration": 4.0},
    )
    clip_id = _clips(client, seq, editor["sub_track"])[0]["id"]

    res = client.post(f"/api/sequences/{seq}/clips/{clip_id}/split", json={"src_time": 2.0})
    assert res.status_code == 200, res.text

    halves = _clips(client, seq, editor["sub_track"])
    assert [h["text_override"] for h in halves] == ["keep me", "keep me"]


def test_cutting_a_range_preserves_speed_gain_and_effects(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    clip_id = _insert_video(editor)
    _dress(client, seq, clip_id)

    res = client.post(f"/api/sequences/{seq}/clips/{clip_id}/cut-range", json={"src_start": 4.0, "src_end": 6.0})
    assert res.status_code == 200, res.text

    pieces = _clips(client, seq, editor["video_track"])
    assert len(pieces) == 2
    for piece in pieces:
        assert piece["speed"] == 2.0, "the transcript-edit path reset the clip to 1x"
        assert piece["gain"] == 0.3
        assert piece["effects"] == {"video_fade": 1.5}


# --------------------------------------------------------------------------------------
# Arithmetic: source duration is not timeline duration once speed != 1
# --------------------------------------------------------------------------------------


def test_split_places_the_right_half_in_timeline_time(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    clip_id = _insert_video(editor)
    client.patch(f"/api/sequences/{seq}/clips/{clip_id}/speed", json={"speed": 2.0})
    # src 0-10 at 2x occupies timeline 0-5. Splitting at src 5 is the timeline midpoint, 2.5.

    assert client.post(f"/api/sequences/{seq}/clips/{clip_id}/split", json={"src_time": 5.0}).status_code == 200

    halves = _clips(client, seq, editor["video_track"])
    assert halves[0]["timeline_start"] == 0.0
    assert halves[1]["timeline_start"] == pytest.approx(2.5), (
        "the right half was placed using the SOURCE delta, so it overhangs the clip's own end "
        "and overwrites whatever followed"
    )


def test_split_and_split_points_agree(editor) -> None:
    """Two routes for the same gesture must not produce different timelines."""
    client, seq = editor["client"], editor["seq"]

    a = _insert_video(editor, start=0.0)
    client.patch(f"/api/sequences/{seq}/clips/{a}/speed", json={"speed": 2.0})
    client.post(f"/api/sequences/{seq}/clips/{a}/split", json={"src_time": 5.0})
    via_split = [c["timeline_start"] for c in _clips(client, seq, editor["video_track"])]

    client.post(f"/api/sequences/{seq}/undo")
    b = _clips(client, seq, editor["video_track"])[0]["id"]
    client.post(f"/api/sequences/{seq}/clips/{b}/split-points", json={"src_times": [5.0]})
    via_points = [c["timeline_start"] for c in _clips(client, seq, editor["video_track"])]

    assert via_split == pytest.approx(via_points)


def test_ripple_delete_closes_the_gap_the_clip_actually_occupied(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    first = _insert_video(editor, start=0.0, src_in=0.0, src_out=10.0)
    client.patch(f"/api/sequences/{seq}/clips/{first}/speed", json={"speed": 2.0})
    # first now occupies timeline 0-5, so removing it should pull a follower back by 5, not 10.
    _insert_video(editor, start=20.0, src_in=0.0, src_out=4.0)

    res = client.delete(f"/api/sequences/{seq}/clips/{first}/ripple")
    assert res.status_code == 200, res.text

    remaining = _clips(client, seq, editor["video_track"])
    assert len(remaining) == 1
    assert remaining[0]["timeline_start"] == pytest.approx(15.0), (
        "the gap was computed in source time, dragging the follower too far left and over "
        "whatever sat before it"
    )


def test_cut_range_places_the_tail_in_timeline_time(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    clip_id = _insert_video(editor)
    client.patch(f"/api/sequences/{seq}/clips/{clip_id}/speed", json={"speed": 2.0})

    assert (
        client.post(f"/api/sequences/{seq}/clips/{clip_id}/cut-range", json={"src_start": 4.0, "src_end": 6.0}).status_code
        == 200
    )

    head, tail = _clips(client, seq, editor["video_track"])
    assert head["timeline_start"] == 0.0
    # head covers src 0-4 at 2x = 2s of timeline, so the tail butts up at 2.0.
    assert tail["timeline_start"] == pytest.approx(2.0)
