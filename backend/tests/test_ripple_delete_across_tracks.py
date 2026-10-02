"""跨轨波纹删除:链接组员同删同左移;「影响所有未锁定轨」时这段时间从整条时间线上拿掉,锁定轨不动。"""

from __future__ import annotations

from tests.test_clips_never_overlap import Timeline
from tests.test_linked_clips import _clip, _detached


def _track(line: Timeline, kind: str) -> str:
    body = line.ok(line.client.post(f"/api/sequences/{line.id}/tracks", json={"kind": kind}))
    return [t for t in body["tracks"] if t["kind"] == kind][-1]["id"]


def _put(line: Timeline, track: str, start: float, length: float, src_in: float = 0.0) -> None:
    line.ok(line.client.post(f"/api/sequences/{line.id}/clips", json={
        "track_id": track, "asset_id": line.asset, "timeline_start": start, "src_in": src_in,
        "src_out": src_in + length}))


def test_波纹删除画面_链接的声音同删_两条轨各自左移_别的轨不动() -> None:
    line = Timeline()
    video, _, audio_track = _detached(line)  # V1 / A1:[2,8)
    _put(line, line.video, 10, 2, src_in=30)
    _put(line, audio_track, 9, 1, src_in=40)
    overlay = _track(line, "video")
    _put(line, overlay, 12, 1, src_in=50)

    after = line.checked(lambda: line.ok(line.client.delete(f"/api/sequences/{line.id}/clips/{video['id']}/ripple")))
    assert _clip(after, line.video) == [(4, 30, 32)]
    assert _clip(after, audio_track) == [(3, 40, 41)], "链接的声音同删,它那条轨上后面的同样左移 6 秒"
    assert _clip(after, overlay) == [(12, 50, 51)], "默认只动被删片段和链接组员自己的轨"

    # 临时解链:只删画面,声音和它那条轨原样。
    line.ok(line.client.post(f"/api/sequences/{line.id}/undo"))
    alone = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/ripple-delete-batch", json={
        "clip_ids": [video["id"]], "linked": False})))
    assert _clip(alone, line.video) == [(4, 30, 32)]
    assert _clip(alone, audio_track) == [(2, 10, 16), (9, 40, 41)]


def test_波纹影响所有未锁定轨_这段时间从整条时间线上拿掉_锁定轨不动() -> None:
    line = Timeline()
    for start, length, src_in in ((0, 4, 0), (4, 4, 10), (8, 2, 20)):
        _put(line, line.video, start, length, src_in)
    music = next(t["id"] for t in line.get()["tracks"] if t["kind"] == "audio")
    _put(line, music, 0, 10, src_in=100)
    subtitles = _track(line, "subtitle")
    for text, start in (("一", 1), ("二", 5), ("三", 8)):
        line.ok(line.client.post(f"/api/sequences/{line.id}/text-clips", json={
            "track_id": subtitles, "text": text, "timeline_start": start, "duration": 1}))
    logo = _track(line, "video")
    _put(line, logo, 6, 1, src_in=200)
    line.ok(line.client.patch(f"/api/sequences/{line.id}/tracks/{logo}", json={"locked": True}))
    middle = line.clips()[1]

    after = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/ripple-delete-batch", json={
        "clip_ids": [middle["id"]], "all_tracks": True})))
    assert _clip(after, line.video) == [(0, 0, 4), (4, 20, 22)]
    assert _clip(after, music) == [(0, 100, 104), (4, 108, 110)], "垫乐里那 4 秒一起拿掉,前后接上"
    cues = sorted(next(t for t in after["tracks"] if t["id"] == subtitles)["clips"], key=lambda c: c["timeline_start"])
    assert [(c["text_override"], c["timeline_start"]) for c in cues] == [("一", 1), ("三", 4)], "落在里面的字幕删掉,后面的跟着左移"
    assert _clip(after, logo) == [(6, 200, 201)], "锁定轨原样不动"

    # 单个删除的接口同样认 all_tracks。
    line.ok(line.client.post(f"/api/sequences/{line.id}/undo"))
    single = line.checked(lambda: line.ok(line.client.delete(
        f"/api/sequences/{line.id}/clips/{middle['id']}/ripple", params={"all_tracks": "true"})))
    assert _clip(single, music) == [(0, 100, 104), (4, 108, 110)]
