"""链接片段:分离音频后,画和声是一组 —— 移动、修剪、切分、删除、变速默认作用于整组。

每一步都过一遍 tests/test_clips_never_overlap 的那道关:之后同轨不重叠、撤销逐字段还原、重做逐字段重来。
`linked=false` 是前端的「临时解链」:这一下只动点中的那段。
"""

from __future__ import annotations

from tests.test_clips_never_overlap import Timeline
from tests.util import create_asset


def _detached(line: Timeline, start: float = 2, length: float = 6, src_in: float = 10):
    """V1 上一段视频,分离音频到 A1。返回 (视频, 音频, 音频轨 id)。"""
    line.put(start, length, src_in=src_in)
    video = line.clips()[0]
    body = line.ok(line.client.post(f"/api/sequences/{line.id}/clips/{video['id']}/detach-audio"))
    audio_track = next(t for t in body["tracks"] if t["kind"] == "audio" and t["clips"])
    return line.clips(body)[0], audio_track["clips"][0], audio_track["id"]


def _clip(body: dict, track_id: str) -> list[tuple[float, float, float]]:
    clips = sorted(next(t for t in body["tracks"] if t["id"] == track_id)["clips"], key=lambda c: c["timeline_start"])
    return [(round(c["timeline_start"], 3), round(c["src_in"], 3), round(c["src_out"], 3)) for c in clips]


def test_分离音频后画和声在同一个链接组() -> None:
    line = Timeline()
    video, audio, _ = _detached(line)
    assert video["link_group"] and video["link_group"] == audio["link_group"]

    undone = line.ok(line.client.post(f"/api/sequences/{line.id}/undo"))
    assert line.clips(undone)[0]["link_group"] is None, "撤销分离,画面也退出那个组"


def test_移动画面_声音跟着平移_临时解链时只动画面() -> None:
    line = Timeline()
    video, _, audio_track = _detached(line)

    moved = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{video['id']}/move", json={"timeline_start": 5})))
    assert _clip(moved, line.video) == [(5, 10, 16)]
    assert _clip(moved, audio_track) == [(5, 10, 16)]

    alone = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{video['id']}/move", json={"timeline_start": 9, "linked": False})))
    assert _clip(alone, line.video) == [(9, 10, 16)]
    assert _clip(alone, audio_track) == [(5, 10, 16)], "临时解链:声音留在原地"

    # 往左拖过头:整组停在最早那段碰到 0 的位置,而不是只把画面压扁到 0。
    left = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{line.clips()[0]['id']}/move", json={"timeline_start": 0})))
    assert _clip(left, line.video) == [(4, 10, 16)]
    assert _clip(left, audio_track) == [(0, 10, 16)]


def test_修剪画面_声音修同一条边_整组一起夹() -> None:
    line = Timeline()
    video, _, audio_track = _detached(line)  # V1 / A1 都是 [2,8),源 10–16

    head = line.checked(lambda: line.ok(line.client.patch(f"/api/sequences/{line.id}/clips/{video['id']}/trim", json={
        "timeline_start": 3, "src_in": 11, "src_out": 16})))
    assert _clip(head, line.video) == [(3, 11, 16)]
    assert _clip(head, audio_track) == [(3, 11, 16)]

    # A1 上紧跟着放一段别的声音:画面的尾巴往右拉,整组停在那段声音的头上。(音频轨上只放音频素材。)
    music = create_asset(line.client, {
        "workspace_id": line.sequence["workspace_id"], "project_id": line.sequence["project_id"], "kind": "audio",
        "name": "M", "file_key": "media/m.wav", "media_info": {"duration": 60}})["id"]
    line.ok(line.client.post(f"/api/sequences/{line.id}/clips", json={
        "track_id": audio_track, "asset_id": music, "timeline_start": 9, "src_in": 40, "src_out": 41}))
    tail = line.checked(lambda: line.ok(line.client.patch(f"/api/sequences/{line.id}/clips/{video['id']}/trim", json={
        "timeline_start": 3, "src_in": 11, "src_out": 25})))
    assert _clip(tail, line.video) == [(3, 11, 17)]
    assert _clip(tail, audio_track) == [(3, 11, 17), (9, 40, 41)]


def test_切开画面_声音在同一刻切开_左半跟左半右半跟右半() -> None:
    line = Timeline()
    video, _, audio_track = _detached(line)

    split = line.checked(lambda: line.ok(line.client.post(
        f"/api/sequences/{line.id}/clips/{video['id']}/split", json={"src_time": 13})))
    assert _clip(split, line.video) == [(2, 10, 13), (5, 13, 16)]
    assert _clip(split, audio_track) == [(2, 10, 13), (5, 13, 16)]
    pieces = {(c["timeline_start"], t["kind"]): c for t in split["tracks"] for c in t["clips"]}
    assert pieces[(2, "video")]["link_group"] == pieces[(2, "audio")]["link_group"]
    assert pieces[(5, "video")]["link_group"] == pieces[(5, "audio")]["link_group"]
    assert pieces[(2, "video")]["link_group"] != pieces[(5, "video")]["link_group"]

    # 拖走右半段的画面,带走的是右半段的声音。
    moved = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{pieces[(5, 'video')]['id']}/move", json={"timeline_start": 20})))
    assert _clip(moved, audio_track) == [(2, 10, 13), (20, 13, 16)]


def test_删除与变速作用于整组() -> None:
    line = Timeline()
    video, _, audio_track = _detached(line)

    slow = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{video['id']}/speed", json={"speed": 0.5})))
    assert {c["speed"] for t in slow["tracks"] for c in t["clips"]} == {0.5}

    kept = line.checked(lambda: line.ok(line.client.delete(
        f"/api/sequences/{line.id}/clips/{video['id']}", params={"linked": "false"})))
    assert _clip(kept, audio_track) == [(2, 10, 16)], "临时解链:只删画面"
    line.ok(line.client.post(f"/api/sequences/{line.id}/undo"))

    gone = line.checked(lambda: line.ok(line.client.delete(f"/api/sequences/{line.id}/clips/{video['id']}")))
    assert all(not t["clips"] for t in gone["tracks"])


def test_锁定轨上的组员不跟着动() -> None:
    line = Timeline()
    video, _, audio_track = _detached(line)
    line.ok(line.client.patch(f"/api/sequences/{line.id}/tracks/{audio_track}", json={"locked": True}))

    moved = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{video['id']}/move", json={"timeline_start": 6})))
    assert _clip(moved, line.video) == [(6, 10, 16)]
    assert _clip(moved, audio_track) == [(2, 10, 16)]
