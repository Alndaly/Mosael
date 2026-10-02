"""按文字剪是真正的波纹删除:同轨后面的左移、链接的音频同步剪、字幕跟着删 / 缩短 / 左移,整批一步撤销。

审查实测(P6):V1 上两段各 10 秒,第一段分离出音频,字幕「前」在 1 秒、「后」在 12 秒;按文字剪掉第一段
源 2–4 秒之后 —— 第二段还在 10 秒、中间留 2 秒黑场;A1 上的音频没剪,音画错开 2 秒;「后」晚了 2 秒。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.unit_of_work import unit_of_work
from app.domain.workflows.executors.subjobs import timeline_cut_ranges
from tests.test_clips_never_overlap import Timeline
from tests.test_linked_clips import _clip, _detached


def _subtitles(line: Timeline, cues: list[tuple[str, float, float]]) -> str:
    body = line.ok(line.client.post(f"/api/sequences/{line.id}/tracks", json={"kind": "subtitle"}))
    track = [t for t in body["tracks"] if t["kind"] == "subtitle"][-1]["id"]
    for text, start, duration in cues:
        line.ok(line.client.post(f"/api/sequences/{line.id}/text-clips", json={
            "track_id": track, "text": text, "timeline_start": start, "duration": duration}))
    return track


def _cues(body: dict, track: str) -> list[tuple[str, float, float]]:
    clips = sorted(next(t for t in body["tracks"] if t["id"] == track)["clips"], key=lambda c: c["timeline_start"])
    return [(c["text_override"], round(c["timeline_start"], 3), round(c["timeline_start"] + c["src_out"] - c["src_in"], 3))
            for c in clips]


def test_审查P6_剪掉2到4秒后_后面的画面_分离的音频_字幕都对齐() -> None:
    line = Timeline()
    first, _, audio_track = _detached(line, start=0, length=10, src_in=0)
    line.ok(line.client.post(f"/api/sequences/{line.id}/append", json={"asset_id": line.asset}))  # 第二段接在 10 秒
    subtitles = _subtitles(line, [("前", 1, 1), ("中", 2.5, 1), ("跨", 3.5, 1), ("后", 12, 1)])

    after = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/cut-ranges", json={
        "cuts": [{"clip_id": first["id"], "ranges": [{"src_start": 2, "src_end": 4}]}]})))

    assert _clip(after, line.video) == [(0, 0, 2), (2, 4, 10), (8, 0, 60)], "第二段从 10 秒左移到 8 秒,不留黑场"
    assert _clip(after, audio_track) == [(0, 0, 2), (2, 4, 10)], "分离出的音频剪掉同样的 2 秒,音画仍对齐"
    assert _cues(after, subtitles) == [("前", 1, 2), ("跨", 2, 2.5), ("后", 10, 11)], (
        "落在删掉区间里的「中」删掉;跨着切口的「跨」只留切口之后那半秒;「后」跟着提前 2 秒")

    # 切开后的右半段:画面和它那截声音是一组,拖走一个带走另一个。
    groups = {(t["kind"], c["timeline_start"]): c["link_group"] for t in after["tracks"] for c in t["clips"]}
    assert groups[("video", 2)] == groups[("audio", 2)] != groups[("video", 0)] == groups[("audio", 0)]


def test_一次剪同一段的好几处_从后往前拿_碎片不留() -> None:
    line = Timeline()
    first, _, audio_track = _detached(line, start=0, length=10, src_in=0)
    line.put(12, 2, src_in=30)

    after = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/{first['id']}/cut-ranges", json={
        # 6–6.02 和 6.04–7 之间那 0.02 秒剩下也只会闪一下:一起拿掉。
        "ranges": [{"src_start": 6.04, "src_end": 7}, {"src_start": 1, "src_end": 2}, {"src_start": 5.5, "src_end": 6.02}]})))
    assert _clip(after, line.video) == [(0, 0, 1), (1, 2, 5.5), (4.5, 7, 10), (9.5, 30, 32)]
    assert _clip(after, audio_track) == [(0, 0, 1), (1, 2, 5.5), (4.5, 7, 10)]


def test_临时解链时只剪画面_锁定的字幕轨不动() -> None:
    line = Timeline()
    first, _, audio_track = _detached(line, start=0, length=10, src_in=0)
    subtitles = _subtitles(line, [("后", 6, 1)])
    line.ok(line.client.patch(f"/api/sequences/{line.id}/tracks/{subtitles}", json={"locked": True}))

    after = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/cut-ranges", json={
        "cuts": [{"clip_id": first["id"], "ranges": [{"src_start": 2, "src_end": 4}]}], "linked": False})))
    assert _clip(after, line.video) == [(0, 0, 2), (2, 4, 10)]
    assert _clip(after, audio_track) == [(0, 0, 10)]
    assert _cues(after, subtitles) == [("后", 6, 7)]


def test_工作流的按时间批量整理走同一个波纹删除() -> None:
    line = Timeline()
    first, _, audio_track = _detached(line, start=0, length=10, src_in=0)
    line.put(10, 2, src_in=30)
    subtitles = _subtitles(line, [("后", 11, 1)])
    workspace = line.get()["workspace_id"]

    scope = SimpleNamespace(workspace_id=workspace, id="wf:1", name="整理")
    with unit_of_work() as db:
        out = timeline_cut_ranges(db, scope, {"sequence_id": line.id, "clip_id": first["id"],
                                              "ranges": [{"src_start": 2, "src_end": 4, "confidence": 1}]})
    assert out["removed_seconds"] == 2.0
    after = line.get()
    assert _clip(after, line.video) == [(0, 0, 2), (2, 4, 10), (8, 30, 32)]
    assert _clip(after, audio_track) == [(0, 0, 2), (2, 4, 10)]
    assert _cues(after, subtitles) == [("后", 9, 10)]
    # 一步撤销整批。
    undone = line.ok(line.client.post(f"/api/sequences/{line.id}/undo"))
    assert _clip(undone, line.video) == [(0, 0, 10), (10, 30, 32)]
    assert _cues(undone, subtitles) == [("后", 11, 12)]
