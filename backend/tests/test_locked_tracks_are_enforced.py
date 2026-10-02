"""锁定的轨,领域层守着:谁都改不了上面的片段,也放不进新的。

此前锁只是剪辑页前端的几行判断。智能体的 edit_timeline、工作流节点、另一个人的剪辑页照样能在锁定
的轨上移动、删除、插入 —— 而用户锁上它,正是不想让这些事发生。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Track
from app.domain.sequences.errors import TrackLocked
from app.domain.sequences.operations import apply_edit_operations
from tests.util import fresh_client, insert_asset


@pytest.fixture()
def locked():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    seq = sequence["id"]
    v1 = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    v2 = next(
        t["id"] for t in client.post(f"/api/sequences/{seq}/tracks", json={"kind": "video"}).json()["tracks"]
        if t["kind"] == "video" and t["id"] != v1
    )
    asset = insert_asset(ws, kind="video", name="v.mp4", file_key="media/v.mp4", media_info={"duration": 20})
    state = client.post(
        f"/api/sequences/{seq}/clips",
        json={"track_id": v1, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 10},
    ).json()
    clip = next(t for t in state["tracks"] if t["id"] == v1)["clips"][0]["id"]
    assert client.patch(f"/api/sequences/{seq}/tracks/{v1}", json={"locked": True}).status_code == 200
    return {"client": client, "ws": ws, "seq": seq, "v1": v1, "v2": v2, "asset": asset, "clip": clip}


def _clips(client, seq):
    return {c["id"]: c for t in client.get(f"/api/sequences/{seq}").json()["tracks"] for c in t["clips"]}


def test_剪辑页的每种改法在锁定轨上都被拒_片段原样不动(locked) -> None:
    client, seq, clip, v1, v2 = locked["client"], locked["seq"], locked["clip"], locked["v1"], locked["v2"]
    before = _clips(client, seq)[clip]
    attempts = [
        client.patch(f"/api/sequences/{seq}/clips/{clip}/move", json={"timeline_start": 30}),
        client.patch(f"/api/sequences/{seq}/clips/{clip}/move", json={"timeline_start": 0, "track_id": v2}),
        client.patch(f"/api/sequences/{seq}/clips/{clip}/trim", json={"timeline_start": 0, "src_in": 0, "src_out": 5}),
        client.post(f"/api/sequences/{seq}/clips/{clip}/split", json={"src_time": 5}),
        client.post(f"/api/sequences/{seq}/clips/{clip}/cut-range", json={"src_start": 2, "src_end": 3}),
        client.patch(f"/api/sequences/{seq}/clips/{clip}/gain", json={"gain": 0.2, "muted": True}),
        client.patch(f"/api/sequences/{seq}/clips/{clip}/effects", json={"effects": {"filter": "bw"}}),
        client.post(f"/api/sequences/{seq}/clips/{clip}/detach-audio"),
        client.delete(f"/api/sequences/{seq}/clips/{clip}"),
        client.delete(f"/api/sequences/{seq}/clips/{clip}/ripple"),
        client.post(f"/api/sequences/{seq}/clips/delete-batch", json={"clip_ids": [clip]}),
        client.post(
            f"/api/sequences/{seq}/clips",
            json={"track_id": v1, "asset_id": locked["asset"], "timeline_start": 12, "src_in": 0, "src_out": 2},
        ),
    ]
    # 删掉整条轨不在此列:那是轨道级的决定,带片段时界面先问过、点了名(with_clips),撤销连锁定状态一起还回来。
    for res in attempts:
        assert res.status_code == 423, (res.request.method, res.request.url, res.status_code, res.text)
    assert _clips(client, seq)[clip] == before


def test_把别的轨上的片段拖进锁定轨被拒(locked) -> None:
    client, seq, v1, v2 = locked["client"], locked["seq"], locked["v1"], locked["v2"]
    state = client.post(
        f"/api/sequences/{seq}/clips",
        json={"track_id": v2, "asset_id": locked["asset"], "timeline_start": 0, "src_in": 0, "src_out": 2},
    ).json()
    other = next(t for t in state["tracks"] if t["id"] == v2)["clips"][0]["id"]
    res = client.patch(f"/api/sequences/{seq}/clips/{other}/move", json={"timeline_start": 15, "track_id": v1})
    assert res.status_code == 423


def test_智能体的编辑同样被拒(locked) -> None:
    with SessionLocal() as db:
        with pytest.raises(TrackLocked):
            apply_edit_operations(db, locked["seq"], [{"kind": "delete_clip", "clip_id": locked["clip"]}])


def test_接到时间线挑没锁的那条同类轨(locked) -> None:
    client, seq = locked["client"], locked["seq"]
    res = client.post(f"/api/sequences/{seq}/append", json={"asset_id": locked["asset"]})
    assert res.status_code == 200, res.text
    v2_clips = next(t for t in res.json()["tracks"] if t["id"] == locked["v2"])["clips"]
    assert len(v2_clips) == 1


def test_解锁后照常能改_撤销不过锁这一道(locked) -> None:
    client, seq, clip, v1 = locked["client"], locked["seq"], locked["clip"], locked["v1"]
    assert client.patch(f"/api/sequences/{seq}/tracks/{v1}", json={"locked": False}).status_code == 200
    assert client.patch(f"/api/sequences/{seq}/clips/{clip}/move", json={"timeline_start": 3}).status_code == 200
    # 移动之后轨道被锁上(这里直接改库,让「移动」仍是撤销栈顶):撤销是在还原已经发生的事,不是新的编辑。
    with SessionLocal() as db:
        db.get(Track, v1).locked = True
        db.commit()
    undone = client.post(f"/api/sequences/{seq}/undo")
    assert undone.status_code == 200, undone.text
    assert _clips(client, seq)[clip]["timeline_start"] == 0
