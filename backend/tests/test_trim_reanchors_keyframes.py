"""修剪之后关键帧还钉在原来那一帧画面上,和切分同一个做法。

关键帧按片段内进度(0=头、1=尾)存。修剪只改出入点不动它们,等于把整条动画压缩 / 拉伸进新的长度:
剪掉后一半,原来在第 5 秒的峰值跑到了第 2.5 秒。
"""

from __future__ import annotations

from tests.util import fresh_client, insert_asset

KEYFRAMES = [{"t": 0, "scale": 1}, {"t": 0.5, "scale": 2}, {"t": 1, "scale": 1}]


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    seq = sequence["id"]
    track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    asset = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 30})
    state = client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": track, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 10}).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["id"]
    assert client.patch(f"/api/sequences/{seq}/clips/{clip}/transform",
                        json={"transform": {"keyframes": KEYFRAMES}}).status_code == 200
    assert client.patch(f"/api/sequences/{seq}/clips/{clip}/effects", json={"effects": {
        "fade_in": 1.0, "gain_keyframes": [{"t": 0, "gain": 0}, {"t": 1, "gain": 1}]}}).status_code == 200
    return client, seq, clip


def _clip(state: dict) -> dict:
    return next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]


def _trim(client, seq, clip, src_in, src_out) -> dict:
    res = client.patch(f"/api/sequences/{seq}/clips/{clip}/trim",
                       json={"timeline_start": 0, "src_in": src_in, "src_out": src_out})
    assert res.status_code == 200, res.text
    return _clip(res.json())


def _points(raw: list[dict], prop: str) -> list[tuple[float, float]]:
    return [(round(p["t"], 3), round(p[prop], 3)) for p in raw]


def test_剪掉后一半_峰值留在原来那一帧_不被压缩进剩下的长度() -> None:
    client, seq, clip = _setup()
    trimmed = _trim(client, seq, clip, 0, 5)
    # 原峰值在源第 5 秒 —— 剪完它就是新片段的尾(进度 1),而不是被压到进度 0.5(第 2.5 秒)。
    assert _points(trimmed["transform"]["keyframes"], "scale") == [(0.0, 1.0), (1.0, 2.0)]
    assert _points(trimmed["effects"]["gain_keyframes"], "gain") == [(0.0, 0.0), (1.0, 0.5)]
    assert trimmed["effects"]["fade_in"] == 1.0, "淡入相对片段的头,修剪之后照样在新的头淡"


def test_拉长时端点钉住_撤销重做连关键帧一起来回() -> None:
    client, seq, clip = _setup()
    _trim(client, seq, clip, 0, 5)
    extended = _trim(client, seq, clip, 0, 10)
    assert _points(extended["transform"]["keyframes"], "scale") == [(0.0, 1.0), (0.5, 2.0), (1.0, 2.0)]

    undone = _clip(client.post(f"/api/sequences/{seq}/undo").json())
    assert _points(undone["transform"]["keyframes"], "scale") == [(0.0, 1.0), (1.0, 2.0)]
    original = _clip(client.post(f"/api/sequences/{seq}/undo").json())
    assert _points(original["transform"]["keyframes"], "scale") == [(0.0, 1.0), (0.5, 2.0), (1.0, 1.0)]
    redone = _clip(client.post(f"/api/sequences/{seq}/redo").json())
    assert _points(redone["transform"]["keyframes"], "scale") == [(0.0, 1.0), (1.0, 2.0)]


def test_只挪位置不改出入点_关键帧不动() -> None:
    client, seq, clip = _setup()
    before = _clip(client.get(f"/api/sequences/{seq}").json())
    res = client.patch(f"/api/sequences/{seq}/clips/{clip}/trim", json={"timeline_start": 3, "src_in": 0, "src_out": 10})
    assert _clip(res.json())["transform"] == before["transform"]


def test_链接的声音跟着修_它的音量曲线也重投影() -> None:
    client, seq, clip = _setup()
    state = client.post(f"/api/sequences/{seq}/clips/{clip}/detach-audio").json()
    audio = next(c for t in state["tracks"] if t["kind"] == "audio" for c in t["clips"])
    assert audio["effects"]["gain_keyframes"]  # 分离时音量曲线跟着声音走
    trimmed = client.patch(f"/api/sequences/{seq}/clips/{clip}/trim",
                           json={"timeline_start": 0, "src_in": 0, "src_out": 5}).json()
    audio = next(c for t in trimmed["tracks"] if t["kind"] == "audio" for c in t["clips"])
    assert audio["src_out"] == 5
    assert _points(audio["effects"]["gain_keyframes"], "gain") == [(0.0, 0.0), (1.0, 0.5)]
