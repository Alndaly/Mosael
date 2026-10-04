"""往画板上追加一张便签(笔记选区工具条的「加到画板」):摆在空位上、不压住已有的格子,记着它是从哪篇笔记来的。

此前画板只能整份存(PATCH /boards/{id},带着 base_revision):笔记页要往一张没打开的画板上放一张卡,就得先把整份
画布拉回来、在浏览器里拼一格、再整份存回去 —— 那张板正开在别处时,这一存就把别人刚挪的位置盖掉。追加一格和
别处的编辑可交换,所以由服务端落在**当前**画布上(和 edit_board、笔记的追加同一个道理)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.model_slices.references import RecordReference
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _board(client, ws: str, items: list[dict] | None = None) -> dict:
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "分镜", "canvas": {"items": items or [], "edges": []}})
    assert created.status_code == 200, created.text
    return created.json()


def _note(client, ws: str) -> dict:
    return client.post("/api/notes", json={"workspace_id": ws, "title": "宣传片周报", "markdown": "周二把脚本写完。"}).json()


def _append(client, ws: str, board_id: str, **body):
    return client.post(f"/api/boards/{board_id}/notes", json={"workspace_id": ws, **body})


def test_追加一张便签_摆在所有格子右边的空位_记着来自哪篇笔记() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board = _board(client, ws, [
        {"id": "a", "kind": "note", "x": 0, "y": 0, "width": 240, "height": 160, "text": "原来的"},
        {"id": "b", "kind": "note", "x": 400, "y": 300, "width": 240, "height": 160, "text": "另一张"},
    ])
    note = _note(client, ws)

    added = _append(client, ws, board["id"], text="周二把脚本写完。",
                    source_note={"note_id": note["id"], "revision": note["revision"], "title": note["title"]})

    assert added.status_code == 200, added.text
    body = added.json()
    after = client.get(f"/api/boards/{board['id']}", params={"workspace_id": ws}).json()
    assert after["revision"] == board["revision"] + 1 == body["revision"]
    items = {one["id"]: one for one in after["canvas"]["items"]}
    assert set(items) == {"a", "b", body["item_id"]}, "原来的格子一张不少"
    card = items[body["item_id"]]
    assert card["kind"] == "note" and card["text"] == "周二把脚本写完。"
    assert card["source_note"] == {"note_id": note["id"], "revision": note["revision"], "title": "宣传片周报"}
    #: 不压住任何一格:左边缘在所有格子的右边缘之外。
    assert card["x"] >= max(one["x"] + one["width"] for one in (items["a"], items["b"]))

    with SessionLocal() as db:
        refs = {(row.target_kind, row.target_id, row.how) for row in db.query(RecordReference).filter(
            RecordReference.source_kind == "board", RecordReference.source_id == board["id"])}
    assert ("note", note["id"], "source") in refs, "引用表里要认得这张卡是从这篇笔记来的(删笔记前查谁还指着它)"


def test_空画板也放得下() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board = _board(client, ws)
    added = _append(client, ws, board["id"], text="第一张")
    assert added.status_code == 200, added.text
    canvas = client.get(f"/api/boards/{board['id']}", params={"workspace_id": ws}).json()["canvas"]
    assert [one["text"] for one in canvas["items"]] == ["第一张"]


def test_来源笔记不在这个工作区_不收() -> None:
    client = fresh_client()
    ws = _workspace(client)
    other = _workspace(client)
    board = _board(client, ws)
    stranger = _note(client, other)

    refused = _append(client, ws, board["id"], text="借来的",
                      source_note={"note_id": stranger["id"], "revision": stranger["revision"], "title": "x"})

    #: 画板领域说不行一律 400(routes/boards._board_http_error),原因写在 detail 里。
    assert refused.status_code == 400, refused.text
    assert "笔记不存在" in refused.json()["detail"]
    assert client.get(f"/api/boards/{board['id']}", params={"workspace_id": ws}).json()["canvas"]["items"] == []


def test_太长的字照便签的上限拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board = _board(client, ws)
    refused = _append(client, ws, board["id"], text="字" * 20_001)
    assert refused.status_code == 400
    assert client.get(f"/api/boards/{board['id']}", params={"workspace_id": ws}).json()["canvas"]["items"] == []


def test_来源只挂在便签上() -> None:
    """来源是「这张卡上的字从哪篇笔记来」;别的格子有自己指向别处的字段(素材、文档),不收它。"""
    client = fresh_client()
    ws = _workspace(client)
    note = _note(client, ws)
    refused = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": [
        {"id": "i", "kind": "image", "x": 0, "y": 0,
         "source_note": {"note_id": note["id"], "revision": note["revision"], "title": "t"}},
    ], "edges": []}})
    assert refused.status_code == 400
    assert "便签" in refused.json()["detail"]
