from __future__ import annotations

from fastapi.testclient import TestClient

from tests.util import fresh_client


def setup_clip(client: TestClient) -> tuple[dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 10}},
    ).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 2, "src_in": 1, "src_out": 9},
    ).json()
    return state, next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]


def clips(sequence: dict) -> list[dict]:
    return sorted(
        next(t for t in sequence["tracks"] if t["kind"] == "video")["clips"],
        key=lambda c: c["timeline_start"],
    )


def test_split_clip_in_two_and_undo() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    # clip: timeline [2,10), src [1,9). Split at src 5 → left [1,5) @2, right [5,9) @6
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/split", json={"src_time": 5}
    ).json()
    left, right = clips(state)
    assert (left["timeline_start"], left["src_in"], left["src_out"]) == (2, 1, 5)
    assert (right["timeline_start"], right["src_in"], right["src_out"]) == (6, 5, 9)

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = clips(undone)
    assert len(restored) == 1 and restored[0]["id"] == clip["id"]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert len(clips(redone)) == 2


def test_split_outside_bounds_rejected() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    for src_time in (1.0, 9.0, 0.5, 20):
        res = client.post(f"/api/sequences/{sequence['id']}/clips/{clip['id']}/split", json={"src_time": src_time})
        assert res.status_code == 422


def test_split_points_divides_into_pieces_and_undo() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)  # timeline [2,10), src [1,9)
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/split-points", json={"src_times": [3, 5, 7]}
    ).json()
    pieces = clips(state)
    # Divided into 4 back-to-back pieces at their original timeline positions — nothing moved.
    assert [(p["timeline_start"], p["src_in"], p["src_out"]) for p in pieces] == [(2, 1, 3), (4, 3, 5), (6, 5, 7), (8, 7, 9)]

    assert len(clips(client.post(f"/api/sequences/{sequence['id']}/undo").json())) == 1
    assert len(clips(client.post(f"/api/sequences/{sequence['id']}/redo").json())) == 4


def test_split_points_ignores_out_of_range_and_too_close() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)  # src [1,9)
    # 0.5 & 20 out of range; 1 & 9 are the ends; 5.02 is <0.05 from 5 → only src=5 survives.
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/split-points",
        json={"src_times": [0.5, 1, 5, 5.02, 9, 20]},
    ).json()
    assert len(clips(state)) == 2


def test_generate_subtitles_batch_and_undo() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    proj = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    seq = client.post("/api/sequences", json={"workspace_id": ws["id"], "project_id": proj["id"], "name": "M"}).json()
    sub = client.post(f"/api/sequences/{seq['id']}/tracks", json={"kind": "subtitle"}).json()
    track = next(t for t in sub["tracks"] if t["kind"] == "subtitle")

    cues = [
        {"text": "第一句", "timeline_start": 0, "duration": 1},
        {"text": "第二句", "timeline_start": 1.2, "duration": 1},
        {"text": "   ", "timeline_start": 3, "duration": 1},  # blank → skipped
    ]
    state = client.post(f"/api/sequences/{seq['id']}/subtitles/generate", json={"track_id": track["id"], "cues": cues}).json()
    clips = next(t for t in state["tracks"] if t["kind"] == "subtitle")["clips"]
    assert len(clips) == 2 and {c["text_override"] for c in clips} == {"第一句", "第二句"}

    undone = client.post(f"/api/sequences/{seq['id']}/undo").json()
    assert next(t for t in undone["tracks"] if t["kind"] == "subtitle")["clips"] == []
    redone = client.post(f"/api/sequences/{seq['id']}/redo").json()
    assert len(next(t for t in redone["tracks"] if t["kind"] == "subtitle")["clips"]) == 2


def test_move_track_reorders_and_undo() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    proj = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    seq = client.post("/api/sequences", json={"workspace_id": ws["id"], "project_id": proj["id"], "name": "M"}).json()
    client.post(f"/api/sequences/{seq['id']}/tracks", json={"kind": "video"})
    state = client.post(f"/api/sequences/{seq['id']}/tracks", json={"kind": "video"}).json()

    ordered = sorted(state["tracks"], key=lambda t: t["position"])
    top, below = ordered[-1], ordered[-2]  # top has the highest position
    moved = client.patch(f"/api/sequences/{seq['id']}/tracks/{top['id']}/move", json={"direction": "up"}).json()
    pos = {t["id"]: t["position"] for t in moved["tracks"]}
    assert pos[top["id"]] < pos[below["id"]]  # they swapped

    undone = client.post(f"/api/sequences/{seq['id']}/undo").json()
    upos = {t["id"]: t["position"] for t in undone["tracks"]}
    assert upos[top["id"]] > upos[below["id"]]  # restored

    # Moving the top-most track further up is a no-op (still 200).
    first = sorted(moved["tracks"], key=lambda t: t["position"])[0]
    assert client.patch(f"/api/sequences/{seq['id']}/tracks/{first['id']}/move", json={"direction": "up"}).status_code == 200


def test_split_points_no_valid_point_rejected() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    res = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/split-points", json={"src_times": [0.5, 20, 9]}
    )
    assert res.status_code == 422


def test_track_mute_lock_with_undo() -> None:
    client = fresh_client()
    sequence, _clip = setup_clip(client)
    track = next(t for t in sequence["tracks"] if t["kind"] == "audio")

    state = client.patch(
        f"/api/sequences/{sequence['id']}/tracks/{track['id']}", json={"muted": True, "locked": True}
    ).json()
    updated = next(t for t in state["tracks"] if t["id"] == track["id"])
    assert updated["muted"] is True and updated["locked"] is True

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    reverted = next(t for t in undone["tracks"] if t["id"] == track["id"])
    assert reverted["muted"] is False and reverted["locked"] is False


def _animated_clip(client: TestClient) -> tuple[dict, dict, str]:
    """一个带位置动画(x: -0.6 → 0.6)的片段,源区间 [0, 8]。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 10}},
    ).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 8},
    ).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]
    client.patch(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/transform",
        json={"transform": {"scale": 0.4, "muted": False,
                            "keyframes": [{"t": 0, "x": -0.6}, {"t": 1, "x": 0.6}]}},
    )
    return sequence, clip, sequence["id"]


def _xs(clip: dict) -> list[tuple[float, float]]:
    return sorted((kf["t"], kf["x"]) for kf in clip["transform"]["keyframes"] if "x" in kf)


def test_split_slices_keyframes_so_animation_stays_continuous() -> None:
    """关键帧 t 是片段内归一化进度,原样复制会让每一段重播整段动画(切点处跳回起点)。

    正中切开后:左段应走完动画的前半(-0.6 → 中点 0.0),右段接着走后半(0.0 → 0.6)。"""
    client = fresh_client()
    sequence, clip, sid = _animated_clip(client)
    state = client.post(f"/api/sequences/{sid}/clips/{clip['id']}/split", json={"src_time": 4}).json()
    left, right = clips(state)
    assert _xs(left) == [(0.0, -0.6), (1.0, 0.0)]
    assert _xs(right) == [(0.0, 0.0), (1.0, 0.6)]
    # 跨切点连续:左段末值 == 右段首值
    assert _xs(left)[-1][1] == _xs(right)[0][1]


def test_split_points_keeps_transform_and_slices_each_piece() -> None:
    """多点切分此前用手写字段表建片段,漏掉 transform/muted/text_override —— 变换整个丢失。"""
    client = fresh_client()
    sequence, clip, sid = _animated_clip(client)
    state = client.post(f"/api/sequences/{sid}/clips/{clip['id']}/split-points",
                        json={"src_times": [2, 6]}).json()
    pieces = clips(state)
    assert len(pieces) == 3
    for piece in pieces:  # 变换不再丢失
        assert piece["transform"].get("scale") == 0.4
    # 三段依次覆盖 -0.6 → -0.3 → 0.3 → 0.6,首尾相接
    assert _xs(pieces[0])[0][1] == -0.6
    assert _xs(pieces[-1])[-1][1] == 0.6
    for earlier, later in zip(pieces, pieces[1:]):
        assert abs(_xs(earlier)[-1][1] - _xs(later)[0][1]) < 1e-6


def test_split_without_keyframes_leaves_transform_untouched() -> None:
    """静态变换(无关键帧)不该被切分改写。"""
    client = fresh_client()
    state, clip = setup_clip(client)
    sid = state["id"]
    client.patch(f"/api/sequences/{sid}/clips/{clip['id']}/transform",
                 json={"transform": {"scale": 0.5, "x": 0.25}})
    split = client.post(f"/api/sequences/{sid}/clips/{clip['id']}/split", json={"src_time": 5}).json()
    for piece in clips(split):
        assert piece["transform"]["scale"] == 0.5
        assert piece["transform"]["x"] == 0.25
