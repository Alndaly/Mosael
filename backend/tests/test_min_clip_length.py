"""片段最短多长只有一个数(MIN_CUT_REMAINDER / too_short),插入让位的切点贴边时也不留重叠。

修剪、切分、覆盖、让位已经认这一个数;新放下的片段和花字此前一个都不查,0.0001 秒的片段放得下去。
"""

from __future__ import annotations

import pytest
from app.domain.sequences.operations import MIN_CUT_REMAINDER
from tests.util import fresh_client, insert_asset


@pytest.fixture()
def editor():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    asset = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 30})
    return client, sequence["id"], track, asset


def _insert(client, seq, track, asset, start, src_in, src_out, ripple=False) -> dict:
    res = client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": track, "asset_id": asset, "timeline_start": start, "src_in": src_in, "src_out": src_out,
        "ripple": ripple})
    assert res.status_code == 200, res.text
    return res.json()


def _spans(state: dict) -> list[tuple[float, float]]:
    clips = sorted(next(t for t in state["tracks"] if t["kind"] == "video")["clips"], key=lambda c: c["timeline_start"])
    return [(round(c["timeline_start"], 3), round(c["timeline_start"] + (c["src_out"] - c["src_in"]) / c["speed"], 3))
            for c in clips]


def _no_overlap(spans: list[tuple[float, float]]) -> bool:
    return all(a_end <= b_start + 1e-9 for (_, a_end), (b_start, _) in zip(spans, spans[1:]))


def test_修剪_切分_插入_花字认同一个最短长度(editor) -> None:
    client, seq, track, asset = editor
    state = _insert(client, seq, track, asset, 0, 0, 10)
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["id"]
    for length, status in ((0.0001, 422), (MIN_CUT_REMAINDER, 422), (MIN_CUT_REMAINDER + 0.01, 200)):
        res = client.patch(f"/api/sequences/{seq}/clips/{clip}/trim",
                           json={"timeline_start": 0, "src_in": 5, "src_out": 5 + length})
        assert res.status_code == status, (length, res.text)
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200
    # 切分:离边多于一个最短长度才切 —— 和修剪是同一个数。
    assert client.post(f"/api/sequences/{seq}/clips/{clip}/split", json={"src_time": 0.04}).status_code == 422
    assert client.post(f"/api/sequences/{seq}/clips/{clip}/split", json={"src_time": 0.06}).status_code == 200
    # 新放下的片段、花字也一样(此前一个都不查,0.0001 秒的片段放得下去)。
    tiny = client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": track, "asset_id": asset, "timeline_start": 20, "src_in": 0, "src_out": 0.01})
    assert tiny.status_code == 422
    tiny_text = client.post(f"/api/sequences/{seq}/text-clips", json={
        "track_id": track, "text": "字", "timeline_start": 30, "duration": 0.01})
    assert tiny_text.status_code == 422


def test_插入让位_切点贴着跨越片段的尾_收尾到落点不留重叠_撤销补回(editor) -> None:
    client, seq, track, asset = editor
    _insert(client, seq, track, asset, 0, 0, 5)
    state = _insert(client, seq, track, asset, 4.97, 0, 2, ripple=True)
    spans = _spans(state)
    assert _no_overlap(spans), spans
    assert spans == [(0, 4.97), (4.97, 6.97)]
    undone = client.post(f"/api/sequences/{seq}/undo").json()
    assert _spans(undone) == [(0, 5)]
    redone = client.post(f"/api/sequences/{seq}/redo").json()
    assert _spans(redone) == [(0, 4.97), (4.97, 6.97)]


def test_插入让位_切点贴着跨越片段的头_它整个右移不留重叠(editor) -> None:
    client, seq, track, asset = editor
    _insert(client, seq, track, asset, 0, 0, 5)
    _insert(client, seq, track, asset, 5, 0, 5)
    state = _insert(client, seq, track, asset, 5.02, 0, 2, ripple=True)
    spans = _spans(state)
    assert _no_overlap(spans), spans
    assert spans == [(0, 5), (5.02, 7.02), (7.02, 12.02)]
    undone = client.post(f"/api/sequences/{seq}/undo").json()
    assert _spans(undone) == [(0, 5), (5, 10)]
