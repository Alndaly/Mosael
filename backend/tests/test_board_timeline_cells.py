"""画板上的时间线格(ADR 0030):格子背后是一条正常的 Mosael 时间线,放在画板自己的同名项目里;连线进来就是接到末尾。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Board, Project, Sequence
from tests.util import board_revision, fresh_client


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "樱花短片"}).json()["id"]
    return client, ws, board


def _asset(ws: str, asset_id: str, kind: str, **info) -> None:
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=ws, kind=kind, name=asset_id, file_key=f"{asset_id}.bin", media_info=info))
        db.commit()


def test_画板第一次建时间线时建同名项目_之后都放进去_画板改名不丢() -> None:
    client, ws, board = _setup()
    first = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})
    assert first.status_code == 200, first.text
    client.patch(f"/api/boards/{board}", json={"workspace_id": ws, "name": "改了名", "base_revision": board_revision(client, board, ws)})
    second = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()
    with SessionLocal() as db:
        project_id = db.get(Board, board).project_id
        project = db.get(Project, project_id)
        assert project.name == "樱花短片" and project.workspace_id == ws
        assert {db.get(Sequence, first.json()["sequence_id"]).project_id, db.get(Sequence, second["sequence_id"]).project_id} == {project_id}
    assert first.json()["name"].endswith("时间线 1") and second["name"].endswith("时间线 2")


def test_项目被删了就再建一个() -> None:
    client, ws, board = _setup()
    client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})
    with SessionLocal() as db:
        old = db.get(Board, board).project_id
    client.delete(f"/api/projects/{old}")
    made = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})
    assert made.status_code == 200, made.text
    with SessionLocal() as db:
        assert db.get(Board, board).project_id not in (None, old)


def test_时间线格存得下_要带_id_别处的时间线存不下() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]

    def save(item):
        return client.patch(f"/api/boards/{board}", json={"workspace_id": ws, "base_revision": board_revision(client, board, ws),
                                                          "canvas": {"items": [item], "edges": []}})

    assert save({"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": sequence}).status_code == 200
    assert save({"id": "t2", "kind": "sequence", "x": 0, "y": 0}).status_code == 400
    other = client.post("/api/workspaces", json={"name": "别处"}).json()["id"]
    other_board = client.post("/api/boards", json={"workspace_id": other, "name": "B"}).json()["id"]
    elsewhere = client.post(f"/api/boards/{other_board}/sequences", json={"workspace_id": other}).json()["sequence_id"]
    refused = save({"id": "t3", "kind": "sequence", "x": 0, "y": 0, "sequence_id": elsewhere})
    assert refused.status_code == 400, refused.text


def test_接到末尾_画幅跟着第一段_音频进音频轨_图片定格五秒() -> None:
    client, ws, board = _setup()
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    _asset(ws, "v1", "video", duration=4.0, width=720, height=1280)
    _asset(ws, "v2", "video", duration=3.0, width=1920, height=1080)
    _asset(ws, "pic", "image", width=720, height=1280)
    _asset(ws, "music", "audio", duration=10.0)
    _asset(ws, "blank", "video")
    for asset_id in ("v1", "v2", "pic", "music"):
        response = client.post(f"/api/sequences/{sequence}/append", json={"asset_id": asset_id})
        assert response.status_code == 200, response.text
    body = response.json()
    assert (body["width"], body["height"]) == (720, 1280), "画幅跟着第一段(竖屏),不跟后面的"
    tracks = {track["kind"]: track for track in body["tracks"]}
    video = sorted(tracks["video"]["clips"], key=lambda clip: clip["timeline_start"])
    assert [(clip["asset_id"], clip["timeline_start"], clip["src_out"]) for clip in video] == [
        ("v1", 0.0, 4.0), ("v2", 4.0, 3.0), ("pic", 7.0, 5.0)]
    assert [(clip["asset_id"], clip["timeline_start"]) for clip in tracks["audio"]["clips"]] == [("music", 0.0)]
    assert client.post(f"/api/sequences/{sequence}/append", json={"asset_id": "blank"}).status_code == 422


def test_迁移_画板记着项目这一列() -> None:
    from app.db.migrations import migration_plan

    assert "migrate-boards-remember-their-project" in {step.name for step in migration_plan().steps}
