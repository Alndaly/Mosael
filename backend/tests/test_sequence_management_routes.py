"""时间线的改名、删除、复制有接口了。

此前三样都没有路由(PATCH / DELETE /api/sequences/{id} 是 405,/duplicate 是 404):项目里建多了
时间线删不掉、名字改不了,想留一版再改只能整个项目复制。领域层的 copy_sequence 早就在,只有画板在用。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Board, Project, Sequence, SequenceOperation
from tests.util import board_revision, fresh_client, insert_asset


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    first = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "主剪"}).json()
    return client, ws, project, first


def test_改名_推版本号_轮询拿得到新名字() -> None:
    client, _ws, project, first = _setup()
    res = client.patch(f"/api/sequences/{first['id']}", json={"name": "终版"})
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "终版" and res.json()["revision"] == first["revision"] + 1
    listed = client.get(f"/api/projects/{project}/sequences").json()
    assert [one["name"] for one in listed] == ["终版"]
    assert client.patch(f"/api/sequences/{first['id']}", json={"name": ""}).status_code == 422


def test_复制_同一个项目里多一条_片段和属性都在_历史不带过去() -> None:
    client, ws, project, first = _setup()
    seq = first["id"]
    track = next(t["id"] for t in first["tracks"] if t["kind"] == "video")
    asset = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 10})
    client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": track, "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 5})
    res = client.post(f"/api/sequences/{seq}/duplicate")
    assert res.status_code == 200, res.text
    copy = res.json()
    assert copy["id"] != seq and copy["project_id"] == project and copy["name"] == "主剪 副本"
    assert [c["asset_id"] for t in copy["tracks"] for c in t["clips"]] == [asset]
    assert copy["can_undo"] is False
    named = client.post(f"/api/sequences/{seq}/duplicate", json={"name": "试剪"}).json()
    assert named["name"] == "试剪"


def test_删除_当前打开的那条换成另一条_最后一条删不掉() -> None:
    client, ws, project, first = _setup()
    second = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "B"}).json()
    with SessionLocal() as db:
        db.get(Project, project).active_sequence_id = first["id"]
        db.commit()
    client.post(f"/api/sequences/{first['id']}/tracks", json={"kind": "audio"})  # 留一点历史,一起删掉
    res = client.delete(f"/api/sequences/{first['id']}")
    assert res.status_code == 204, res.text
    with SessionLocal() as db:
        assert db.get(Sequence, first["id"]) is None
        assert db.get(Project, project).active_sequence_id == second["id"]
        assert db.query(SequenceOperation).filter(SequenceOperation.sequence_id == first["id"]).count() == 0
    last = client.delete(f"/api/sequences/{second['id']}")
    assert last.status_code == 422
    assert "最后一条" in last.json()["detail"] or "last timeline" in last.json()["detail"]


def test_画板上还摆着的时间线删不掉_点名是哪张画板() -> None:
    client, ws, _project, _first = _setup()
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "樱花短片"}).json()["id"]
    sequence = client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws}).json()["sequence_id"]
    client.post(f"/api/boards/{board}/sequences", json={"workspace_id": ws})  # 同项目里另一条,免得撞上「最后一条」
    client.patch(f"/api/boards/{board}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board, ws),
        "canvas": {"items": [{"id": "t", "kind": "sequence", "x": 0, "y": 0, "sequence_id": sequence}], "edges": []}})
    res = client.delete(f"/api/sequences/{sequence}")
    assert res.status_code == 422
    assert "樱花短片" in res.json()["detail"]
    with SessionLocal() as db:
        assert db.get(Sequence, sequence) is not None and db.get(Board, board) is not None


def test_没有编辑权限的人改不了也删不了() -> None:
    from tests.util import second_client

    client, _ws, _project, first = _setup()
    stranger = second_client("stranger")
    assert stranger.patch(f"/api/sequences/{first['id']}", json={"name": "x"}).status_code in (403, 404)
    assert stranger.delete(f"/api/sequences/{first['id']}").status_code in (403, 404)
    assert stranger.post(f"/api/sequences/{first['id']}/duplicate").status_code in (403, 404)
