from __future__ import annotations

from tests.test_ripple_delete import setup_three_clips, video_clips
from tests.util import fresh_client


def test_ripple_move_pushes_followers_and_undoes() -> None:
    client = fresh_client()
    sequence, clips = setup_three_clips(client)  # A@0 len4, B@5 len3, C@10 len2
    c = clips[2]  # C, duration 2

    # Insert C at t=5 with ripple → B (starts >= 5) pushed right by C's duration (2).
    state = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{c['id']}/move",
        json={"timeline_start": 5, "ripple": True},
    ).json()
    assert [round(x["timeline_start"], 3) for x in video_clips(state)] == [0, 5, 7]  # A, C, B

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert [x["timeline_start"] for x in video_clips(undone)] == [0, 5, 10]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert [round(x["timeline_start"], 3) for x in video_clips(redone)] == [0, 5, 7]


def test_move_without_ripple_leaves_others() -> None:
    client = fresh_client()
    sequence, clips = setup_three_clips(client)
    c = clips[2]  # C @10

    # Overwrite mode: plain move, no one else shifts (clips may overlap freely).
    state = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{c['id']}/move",
        json={"timeline_start": 5},
    ).json()
    assert sorted(round(x["timeline_start"], 3) for x in video_clips(state)) == [0, 5, 5]
