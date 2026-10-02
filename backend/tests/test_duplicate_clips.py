"""复制片段:位置之外的一切照原样,可以一次复制好几段,整批一步撤销。

前端此前要自己拼一个 insert_clip 去「复制」:只带得过去素材和出入点,速度、调色、关键帧、花字的文字
全没了;复制字幕 / 花字(没有素材)根本插不进去。
"""

from __future__ import annotations

import pytest

from tests.util import fresh_client, insert_asset


@pytest.fixture()
def editor():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    seq = sequence["id"]
    state = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "subtitle"}).json()
    tracks = {t["kind"]: t["id"] for t in state["tracks"] if t["kind"] != "video"}
    tracks["video"] = next(t["id"] for t in state["tracks"] if t["name"] == "V1")
    asset = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 30})
    state = client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": tracks["video"], "asset_id": asset, "timeline_start": 2, "src_in": 1, "src_out": 9}).json()
    video = next(t for t in state["tracks"] if t["id"] == tracks["video"])["clips"][0]["id"]
    client.patch(f"/api/sequences/{seq}/clips/{video}/speed", json={"speed": 2})
    client.patch(f"/api/sequences/{seq}/clips/{video}/gain", json={"gain": 0.4, "muted": True})
    client.patch(f"/api/sequences/{seq}/clips/{video}/effects", json={"effects": {"filter": "bw", "fade_in": 0.5}})
    client.patch(f"/api/sequences/{seq}/clips/{video}/transform",
                 json={"transform": {"scale": 1.5, "keyframes": [{"t": 0, "x": 0}, {"t": 1, "x": 0.2}]}})
    state = client.post(f"/api/sequences/{seq}/text-clips", json={
        "track_id": tracks["subtitle"], "text": "你好", "timeline_start": 3, "duration": 2}).json()
    subtitle = next(t for t in state["tracks"] if t["kind"] == "subtitle")["clips"][0]["id"]
    return client, seq, tracks, video, subtitle


def _clips(state: dict, track_id: str) -> list[dict]:
    return sorted(next(t for t in state["tracks"] if t["id"] == track_id)["clips"], key=lambda c: c["timeline_start"])


CARRIED = ("asset_id", "src_in", "src_out", "speed", "gain", "muted", "effects", "transform", "text_override", "offline_asset")


def test_一次复制好几段_属性照原样_接在原片段组之后_相对位置不变(editor) -> None:
    client, seq, tracks, video, subtitle = editor
    res = client.post(f"/api/sequences/{seq}/clips/duplicate", json={"clip_ids": [video, subtitle]})
    assert res.status_code == 200, res.text
    state = res.json()
    original_video, copied_video = _clips(state, tracks["video"])
    original_sub, copied_sub = _clips(state, tracks["subtitle"])
    for field in CARRIED:
        assert copied_video[field] == original_video[field], field
        assert copied_sub[field] == original_sub[field], field
    # 原片段组 [2, 6)(视频 8 秒素材 2 倍速 = 4 秒),副本组从 6 开始,字幕仍比视频晚 1 秒。
    assert (copied_video["timeline_start"], copied_sub["timeline_start"]) == (6.0, 7.0)
    assert copied_video["id"] not in (video, subtitle)


def test_复制到指定的位置和轨_撤销一步全部拿掉_重做再回来(editor) -> None:
    client, seq, tracks, video, _subtitle = editor
    state = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "video"}).json()
    v2 = next(t["id"] for t in state["tracks"] if t["name"] == "V2")
    state = client.post(f"/api/sequences/{seq}/clips/duplicate",
                        json={"clip_ids": [video], "timeline_start": 20, "track_id": v2}).json()
    (copy,) = _clips(state, v2)
    assert copy["timeline_start"] == 20 and copy["effects"]["filter"] == "bw"

    undone = client.post(f"/api/sequences/{seq}/undo").json()
    assert _clips(undone, v2) == [] and len(_clips(undone, tracks["video"])) == 1
    redone = client.post(f"/api/sequences/{seq}/redo").json()
    assert [c["id"] for c in _clips(redone, v2)] == [copy["id"]]


def test_副本和原片互不影响(editor) -> None:
    client, seq, tracks, video, _subtitle = editor
    state = client.post(f"/api/sequences/{seq}/clips/duplicate", json={"clip_ids": [video]}).json()
    _original, copy = _clips(state, tracks["video"])
    client.patch(f"/api/sequences/{seq}/clips/{copy['id']}/effects", json={"effects": {"filter": "warm"}})
    state = client.get(f"/api/sequences/{seq}").json()
    assert _clips(state, tracks["video"])[0]["effects"]["filter"] == "bw"


def test_放不进的轨被拒(editor) -> None:
    client, seq, tracks, video, _subtitle = editor
    wrong_kind = client.post(f"/api/sequences/{seq}/clips/duplicate",
                             json={"clip_ids": [video], "track_id": tracks["audio"]})
    assert wrong_kind.status_code == 422
    client.patch(f"/api/sequences/{seq}/tracks/{tracks['video']}", json={"locked": True})
    locked = client.post(f"/api/sequences/{seq}/clips/duplicate", json={"clip_ids": [video]})
    assert locked.status_code == 423


def test_复制到有片段的地方是覆盖_同轨不叠(editor) -> None:
    client, seq, tracks, video, _subtitle = editor
    state = client.get(f"/api/sequences/{seq}").json()
    asset = _clips(state, tracks["video"])[0]["asset_id"]
    client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": tracks["video"], "asset_id": asset, "timeline_start": 10, "src_in": 0, "src_out": 4})
    state = client.post(f"/api/sequences/{seq}/clips/duplicate", json={"clip_ids": [video], "timeline_start": 11}).json()
    spans = [(c["timeline_start"], c["timeline_start"] + (c["src_out"] - c["src_in"]) / c["speed"])
             for c in _clips(state, tracks["video"])]
    assert spans == [(2, 6), (10, 11), (11, 15)], "被副本盖住的那段裁到副本的头上"
    undone = client.post(f"/api/sequences/{seq}/undo").json()
    assert [(c["timeline_start"], c["src_out"]) for c in _clips(undone, tracks["video"])] == [(2, 9), (10, 4)]


def test_一起复制的链接组员在副本里自成一组_只复制一段的不进任何组(editor) -> None:
    client, seq, tracks, video, _subtitle = editor
    state = client.post(f"/api/sequences/{seq}/clips/{video}/detach-audio").json()
    audio = next(c for t in state["tracks"] if t["kind"] == "audio" for c in t["clips"])
    group = audio["link_group"]
    both = client.post(f"/api/sequences/{seq}/clips/duplicate", json={"clip_ids": [video, audio["id"]]}).json()
    copies = [c for t in both["tracks"] for c in t["clips"] if c["id"] not in (video, audio["id"]) and c["asset_id"]]
    assert len(copies) == 2 and copies[0]["link_group"] == copies[1]["link_group"] != group
    alone = client.post(f"/api/sequences/{seq}/clips/duplicate", json={"clip_ids": [video], "timeline_start": 40}).json()
    copy = next(c for c in _clips(alone, tracks["video"]) if c["timeline_start"] == 40)
    assert copy["link_group"] is None
