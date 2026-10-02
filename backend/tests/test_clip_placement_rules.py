"""放片段只有一套规矩:轨道要对得上素材,出点不超过素材末尾。

此前只有工作流的「接到时间线」查这两样;剪辑页和智能体的插入都不查 —— 视频能进音频轨(画面静默
地没了)、字幕轨能放素材、10 秒的素材能插成 100 秒的片段(后 90 秒是空白),修剪也能往外拉出空白。
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
    tracks = {t["kind"]: t["id"] for t in state["tracks"]}
    return {
        "client": client,
        "seq": seq,
        "tracks": tracks,
        "video": insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 10}),
        "audio": insert_asset(ws, kind="audio", name="a", file_key="y", media_info={"duration": 10}),
        "image": insert_asset(ws, kind="image", name="i", file_key="z", media_info={"width": 100, "height": 100}),
    }


def _insert(editor, track_kind: str, asset_kind: str, **span):
    body = {"track_id": editor["tracks"][track_kind], "asset_id": editor[asset_kind], "timeline_start": 0,
            "src_in": 0, "src_out": 5, **span}
    return editor["client"].post(f"/api/sequences/{editor['seq']}/clips", json=body)


@pytest.mark.parametrize(
    ("track_kind", "asset_kind"),
    [("audio", "video"), ("video", "audio"), ("subtitle", "video"), ("audio", "image")],
)
def test_素材进不了不对的轨(editor, track_kind, asset_kind) -> None:
    res = _insert(editor, track_kind, asset_kind)
    assert res.status_code == 422, res.text
    assert "track" in res.json()["detail"] or "轨道" in res.json()["detail"]


def test_出点夹到素材末尾_入点在末尾之后被拒(editor) -> None:
    state = _insert(editor, "video", "video", src_out=100).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]
    assert clip["src_out"] == 10
    assert _insert(editor, "audio", "audio", src_in=50, src_out=60).status_code == 422


def test_图片没有末尾_定格多久由调用方说了算(editor) -> None:
    state = _insert(editor, "video", "image", src_in=50, src_out=60).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]
    assert (clip["src_in"], clip["src_out"]) == (50, 60)


def test_修剪往外拉也拉不过素材末尾_撤销还回原样(editor) -> None:
    client, seq = editor["client"], editor["seq"]
    state = _insert(editor, "video", "video").json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["id"]
    trimmed = client.patch(
        f"/api/sequences/{seq}/clips/{clip}/trim", json={"timeline_start": 0, "src_in": 0, "src_out": 40}
    ).json()
    assert next(t for t in trimmed["tracks"] if t["kind"] == "video")["clips"][0]["src_out"] == 10
    redo_target = client.post(f"/api/sequences/{seq}/undo").json()
    assert next(t for t in redo_target["tracks"] if t["kind"] == "video")["clips"][0]["src_out"] == 5
    redone = client.post(f"/api/sequences/{seq}/redo").json()
    assert next(t for t in redone["tracks"] if t["kind"] == "video")["clips"][0]["src_out"] == 10
