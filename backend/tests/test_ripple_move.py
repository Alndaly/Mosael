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


def test_ripple_move_only_shifts_by_actual_overlap() -> None:
    # Regression: a tiny nudge in insert mode used to shove every downstream clip
    # right by the moved clip's FULL duration, exploding the timeline.
    client = fresh_client()
    sequence, clips = setup_three_clips(client)  # A@0 len4, B@5 len3, C@10 len2
    a = clips[0]  # len 4

    # Nudge A 0 -> 0.5: A[0.5,4.5) does not reach B@5, so nothing else moves.
    state = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{a['id']}/move",
        json={"timeline_start": 0.5, "ripple": True},
    ).json()
    assert [round(x["timeline_start"], 2) for x in video_clips(state)] == [0.5, 5, 10]

    # Move A 0 -> 3: A[3,7) overlaps B@5 by 2 → B and C shift right by exactly 2,
    # gap between B and C preserved (5→7, 10→12).
    state = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{a['id']}/move",
        json={"timeline_start": 3, "ripple": True},
    ).json()
    assert [round(x["timeline_start"], 2) for x in video_clips(state)] == [3, 7, 12]


def test_ripple_move_splits_straddled_clip_and_undoes() -> None:
    """落点插进一个片段的身体里(它先于落点开始、延伸过落点):真正的插入编辑要在
    落点切开它、尾段随下游让位 — 否则尾段被移入片段覆盖("插入模式还是覆盖")。"""
    client = fresh_client()
    sequence, clips = setup_three_clips(client)  # A@0 len4, B@5 len3, C@10 len2
    c = clips[2]  # C, duration 2

    # C 插到 t=2,落在 A[0,4) 身体里 → A 在 2 处切开:A 头 [0,2) 留原位,
    # 尾段与 B 一起右移 C 的时长(2):尾段 2→4、B 5→7。
    state = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{c['id']}/move",
        json={"timeline_start": 2, "ripple": True},
    ).json()
    ordered = video_clips(state)
    assert [round(x["timeline_start"], 3) for x in ordered] == [0, 2, 4, 7]  # A头, C, A尾, B
    head, moved, tail, b = ordered
    assert round(head["src_out"], 3) == 2 and round(tail["src_in"], 3) == 2 and round(tail["src_out"], 3) == 4
    assert moved["id"] == c["id"]

    # 撤销:尾段消失、A 的 src_out 补回 4,一切归位。
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = video_clips(undone)
    assert [x["timeline_start"] for x in restored] == [0, 5, 10]
    assert round(restored[0]["src_out"], 3) == 4

    # 重做:重新切开 + 让位,与首次结果一致(尾段沿用原 id)。
    redo_res = client.post(f"/api/sequences/{sequence['id']}/redo")
    assert redo_res.status_code == 200, redo_res.text
    redone = redo_res.json()
    assert [round(x["timeline_start"], 3) for x in video_clips(redone)] == [0, 2, 4, 7]
    assert video_clips(redone)[2]["id"] == tail["id"]


def test_ripple_insert_from_pool_makes_room() -> None:
    """插入模式下素材落轨与移动同语义:切开落点上的片段并让位,而不是覆盖。"""
    client = fresh_client()
    sequence, clips = setup_three_clips(client)  # A@0 len4, B@5 len3, C@10 len2
    track_id = clips[0]["track_id"]
    asset_id = clips[0]["asset_id"]

    # 新素材片段(len 1)插到 t=1,落在 A 身体里 → A 头 [0,1) + 尾段右移 1 到 t=2,B/C 各 +1。
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track_id, "asset_id": asset_id, "timeline_start": 1, "src_in": 0, "src_out": 1, "ripple": True},
    ).json()
    assert [round(x["timeline_start"], 3) for x in video_clips(state)] == [0, 1, 2, 6, 11]

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = video_clips(undone)
    assert [x["timeline_start"] for x in restored] == [0, 5, 10]
    assert round(restored[0]["src_out"], 3) == 4


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
