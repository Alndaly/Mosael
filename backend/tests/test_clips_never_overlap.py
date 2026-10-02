"""不变量:**任何编辑之后,同一条轨上的片段都不重叠**;撤销把被裁、被切、被删的片段原样还回来。

预览和导出都假定同轨不重叠(media/scene.py 的 active_clip_on_track),而此前非波纹的插入 / 移动、
修剪拉进邻居、慢放都能造出重叠 —— 叠着的时候先开始的那段赢,后放上去的那段看不见。

每条用例都走真的接口:做一步 → 查不变量 → 撤销,整条时间线(每段的位置、源区间、倍速、变换、调色)
和做之前逐字段相同 → 重做,和做完那一刻逐字段相同。
"""

from __future__ import annotations

from typing import Any

from tests.util import create_asset, fresh_client

EPS = 1e-6


def _end(clip: dict[str, Any]) -> float:
    return clip["timeline_start"] + (clip["src_out"] - clip["src_in"]) / (clip["speed"] or 1.0)


def assert_no_overlap(sequence: dict[str, Any]) -> None:
    for track in sequence["tracks"]:
        clips = sorted(track["clips"], key=lambda clip: clip["timeline_start"])
        for before, after in zip(clips, clips[1:]):
            assert _end(before) <= after["timeline_start"] + EPS, (
                f"{track['name']} 上 {before['id'][:6]} 到 {_end(before):.3f},"
                f"{after['id'][:6]} 从 {after['timeline_start']:.3f} 开始 —— 叠在一起了"
            )


def snapshot(sequence: dict[str, Any]) -> dict[str, list[tuple]]:
    fields = ("id", "timeline_start", "src_in", "src_out", "speed", "muted", "transform", "effects", "text_override")
    return {
        track["id"]: sorted(
            tuple(round(clip[name], 6) if isinstance(clip[name], float) else repr(clip[name]) for name in fields)
            for clip in track["clips"]
        )
        for track in sequence["tracks"]
    }


class Timeline:
    def __init__(self) -> None:
        self.client = fresh_client()
        ws = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        project = self.client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
        self.asset = create_asset(self.client, {"workspace_id": ws, "project_id": project, "kind": "video", "name": "V",
                                                "file_key": "media/v.mp4", "media_info": {"duration": 60}})["id"]
        self.sequence = self.client.post(
            "/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}
        ).json()
        self.id = self.sequence["id"]
        self.video = next(t for t in self.sequence["tracks"] if t["kind"] == "video")["id"]

    def get(self) -> dict[str, Any]:
        return self.client.get(f"/api/sequences/{self.id}").json()

    def put(self, start: float, length: float, *, src_in: float = 0.0, ripple: bool = False) -> dict[str, Any]:
        return self.ok(self.client.post(f"/api/sequences/{self.id}/clips", json={
            "track_id": self.video, "asset_id": self.asset, "timeline_start": start,
            "src_in": src_in, "src_out": src_in + length, "ripple": ripple}))

    def ok(self, response) -> dict[str, Any]:
        assert response.status_code == 200, response.text
        return response.json()

    def clips(self, sequence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        sequence = sequence or self.get()
        track = next(t for t in sequence["tracks"] if t["id"] == self.video)
        return sorted(track["clips"], key=lambda clip: clip["timeline_start"])

    def spans(self, sequence: dict[str, Any] | None = None) -> list[tuple[float, float, float, float]]:
        """(起点, 终点, 入点, 出点),按起点排。"""
        return [
            (round(c["timeline_start"], 3), round(_end(c), 3), round(c["src_in"], 3), round(c["src_out"], 3))
            for c in self.clips(sequence)
        ]

    def checked(self, edit) -> dict[str, Any]:
        """做一步编辑,并钉住:之后不重叠、撤销逐字段还原、重做逐字段重来。"""
        before = snapshot(self.get())
        after = edit()
        assert_no_overlap(after)
        undone = self.ok(self.client.post(f"/api/sequences/{self.id}/undo"))
        assert snapshot(undone) == before, "撤销没有把时间线原样还回来"
        redone = self.ok(self.client.post(f"/api/sequences/{self.id}/redo"))
        assert snapshot(redone) == snapshot(after), "重做和第一次做的结果不一样"
        return redone


def test_覆盖插入_盖住整段的删掉_盖住一头的裁掉_落在中间的切成两段() -> None:
    line = Timeline()
    line.put(0, 4)
    line.put(5, 3)
    line.put(10, 6, src_in=10)

    after = line.checked(lambda: line.put(3, 9))  # [3,12):盖住 A 的尾、整个 B、C 的头
    assert line.spans(after) == [(0, 3, 0, 3), (3, 12, 0, 9), (12, 16, 12, 16)]

    after = line.checked(lambda: line.put(5, 2))  # 落在刚放下那段的中间 → 切成两段
    assert line.spans(after) == [(0, 3, 0, 3), (3, 5, 0, 2), (5, 7, 0, 2), (7, 12, 4, 9), (12, 16, 12, 16)]


def test_覆盖切开的两半各自带着自己那一截的关键帧() -> None:
    line = Timeline()
    clip = line.put(0, 10)["tracks"]
    clip_id = next(t for t in clip if t["id"] == line.video)["clips"][0]["id"]
    line.ok(line.client.patch(f"/api/sequences/{line.id}/clips/{clip_id}/transform", json={
        "transform": {"keyframes": [{"t": 0, "opacity": 0}, {"t": 1, "opacity": 1}]}}))

    after = line.checked(lambda: line.put(4, 2))
    left, _, right = line.clips(after)
    assert [round(k["opacity"], 3) for k in left["transform"]["keyframes"]] == [0, 0.4]
    assert [round(k["opacity"], 3) for k in right["transform"]["keyframes"]] == [0.6, 1]


def test_插入模式贴着跨越片段的边_不留下一点重叠() -> None:
    """审查实测 E18:落点离跨越片段的尾巴只有 0.03 秒,切不开 —— 以前就叠着那 0.03 秒。"""
    line = Timeline()
    line.put(0, 5)
    line.put(5, 3, src_in=20)

    after = line.checked(lambda: line.put(4.97, 2, ripple=True))
    assert line.spans(after) == [(0, 4.97, 0, 4.97), (4.97, 6.97, 0, 2), (6.97, 9.97, 20, 23)]

    line = Timeline()
    line.put(0, 5)
    after = line.checked(lambda: line.put(0.02, 2, ripple=True))  # 贴着它的头:整段让开,而不是切出一截碎片
    assert line.spans(after) == [(0.02, 2.02, 0, 2), (2.02, 7.02, 0, 5)]


def test_移动是覆盖_整组拖到一起时后开始的盖住先开始的() -> None:
    line = Timeline()
    for start, length in ((0, 4), (5, 3), (10, 2)):
        line.put(start, length)
    a, b, c = line.clips()

    after = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{c['id']}/move", json={"timeline_start": 1})))
    assert line.spans(after) == [(0, 1, 0, 1), (1, 3, 0, 2), (3, 4, 3, 4), (5, 8, 0, 3)]

    line = Timeline()
    for start, length in ((0, 4), (5, 3), (10, 2)):
        line.put(start, length)
    a, b, c = line.clips()
    after = line.checked(lambda: line.ok(line.client.patch(f"/api/sequences/{line.id}/clips/move-batch", json={
        "moves": [{"clip_id": b["id"], "timeline_start": 20}, {"clip_id": c["id"], "timeline_start": 21}]})))
    assert line.spans(after) == [(0, 4, 0, 4), (20, 21, 0, 1), (21, 23, 0, 2)]


def test_修剪拉进邻居时夹到邻居的边上() -> None:
    line = Timeline()
    line.put(0, 4, src_in=10)
    line.put(5, 3, src_in=20)
    line.put(10, 2, src_in=30)
    _, b, _ = line.clips()

    # 头往左拉过 A 的尾(4),尾往右拉过 C 的头(10):两头都停在邻居的边上。
    after = line.checked(lambda: line.ok(line.client.patch(f"/api/sequences/{line.id}/clips/{b['id']}/trim", json={
        "timeline_start": 2, "src_in": 17, "src_out": 30})))
    assert line.spans(after) == [(0, 4, 10, 14), (4, 10, 19, 25), (10, 12, 30, 32)]


def test_变速默认推开或拉回后面的片段() -> None:
    line = Timeline()
    line.put(0, 4)
    line.put(5, 3, src_in=20)
    line.put(9, 2, src_in=30)
    a, _, _ = line.clips()

    slow = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{a['id']}/speed", json={"speed": 0.5})))
    assert line.spans(slow) == [(0, 8, 0, 4), (9, 12, 20, 23), (13, 15, 30, 32)], "慢放:后面的整体推开 4 秒,间距保留"

    fast = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{a['id']}/speed", json={"speed": 2})))
    assert line.spans(fast) == [(0, 2, 0, 4), (3, 6, 20, 23), (7, 9, 30, 32)], "快放:后面的整体拉回,不留空白"


def test_变速不推开时_慢放会盖住下一段就拒绝_什么都不改() -> None:
    line = Timeline()
    line.put(0, 4)
    line.put(5, 3, src_in=20)
    a, _ = line.clips()
    before = snapshot(line.get())

    refused = line.client.patch(f"/api/sequences/{line.id}/clips/{a['id']}/speed", json={"speed": 0.5, "ripple": False})
    assert refused.status_code == 422, refused.text
    assert snapshot(line.get()) == before

    # 放得下的慢放照常生效,后面的不动。
    after = line.checked(lambda: line.ok(line.client.patch(
        f"/api/sequences/{line.id}/clips/{a['id']}/speed", json={"speed": 0.8, "ripple": False})))
    assert line.spans(after) == [(0, 5, 0, 4), (5, 8, 20, 23)]


def test_字幕与花字也按覆盖落位() -> None:
    line = Timeline()
    subtitle = next(t for t in line.ok(line.client.post(
        f"/api/sequences/{line.id}/tracks", json={"kind": "subtitle"}))["tracks"] if t["kind"] == "subtitle")["id"]
    line.ok(line.client.post(f"/api/sequences/{line.id}/text-clips", json={
        "track_id": subtitle, "text": "第一句", "timeline_start": 0, "duration": 3}))

    after = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/text-clips", json={
        "track_id": subtitle, "text": "第二句", "timeline_start": 2, "duration": 3})))
    cues = sorted(next(t for t in after["tracks"] if t["id"] == subtitle)["clips"], key=lambda c: c["timeline_start"])
    assert [(c["text_override"], c["timeline_start"], _end(c)) for c in cues] == [("第一句", 0, 2), ("第二句", 2, 5)]

    after = line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/subtitles/generate", json={
        "track_id": subtitle, "cues": [{"text": "甲", "timeline_start": 1, "duration": 2},
                                       {"text": "乙", "timeline_start": 2.5, "duration": 2}]})))
    cues = sorted(next(t for t in after["tracks"] if t["id"] == subtitle)["clips"], key=lambda c: c["timeline_start"])
    assert [(c["text_override"], round(c["timeline_start"], 3), round(_end(c), 3)) for c in cues] == [
        ("第一句", 0, 1), ("甲", 1, 2.5), ("乙", 2.5, 4.5), ("第二句", 4.5, 5)]


def test_其余算子之后也守着不变量() -> None:
    """切分、按文字剪、波纹删除、删除、分离音频、接到末尾:各做一遍,都过一遍不变量与撤销完整性。"""
    line = Timeline()
    for start, length, src_in in ((0, 4, 0), (4, 6, 10), (12, 3, 30)):
        line.put(start, length, src_in=src_in)
    a, b, c = line.clips()

    line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/{b['id']}/split", json={"src_time": 12})))
    b1 = line.clips()[1]
    line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/cut-ranges", json={
        "cuts": [{"clip_id": b1["id"], "ranges": [{"src_start": 10.5, "src_end": 11}]}]})))
    line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/{a['id']}/detach-audio")))
    line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/append", json={"asset_id": line.asset})))
    line.checked(lambda: line.ok(line.client.delete(f"/api/sequences/{line.id}/clips/{c['id']}/ripple")))
    line.checked(lambda: line.ok(line.client.post(f"/api/sequences/{line.id}/clips/delete-batch",
                                                   json={"clip_ids": [a["id"]]})))
