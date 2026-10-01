"""画板上「让 AI 写」认资产,文档格也会写。

- 便签:连进来的资产格、正文里 `@` 到的资产,描述当材料交给模型,前几张参考图给模型看 —— 和生成里的 `@资产`
  同一份画像。此前写字只认素材和便签的字,连一个人物进来什么都不带。
- 文档格:写出来的是一篇笔记。空的新建一篇并引用它;引用着一篇的写成它的新一版,文档格钉到新的那一版。
- 连进来的便签和文档:它们的字由服务端按连线取(actions.upstream_texts),表单里只有用户那句。此前是前端把正文
  拼成 `context` 交上来,给模型什么由前端说了算,和生成读文档是两套。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch as mock_patch

from app.core.db import SessionLocal
from tests.test_board_generation_documents import _parsed_document
from tests.test_boards import _workspace, _writable_profile
from tests.util import fresh_client, run_on_board_settled, seed_assets


class Seen:
    """记下交给模型的对话和让它看的素材(模型、读素材都换成假的)。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.messages: list[dict[str, Any]] = []
        self.looked_at: list[str] = []
        self.options: dict[str, Any] = {}

    def chat(self, target, messages, **kwargs):
        self.messages = messages
        self.options = kwargs
        return self.reply

    def look_at(self, db, workspace_id, asset_ids):
        self.looked_at = list(asset_ids)
        return [], []

    def text(self) -> str:
        return "\n".join(str(one["content"]) for one in self.messages)


def _board(client, ws: str, items: list[dict], edges: list[dict] | None = None) -> str:
    made = client.post("/api/boards", json={"workspace_id": ws, "canvas": {"items": items, "edges": edges or []}})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _person(client, ws: str, name: str, refs: tuple[str, ...]) -> str:
    made = client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": name,
                                              "description": "班长", "prompt": "short hair, school uniform"}).json()
    for asset_id in refs:
        client.post(f"/api/entities/{made['id']}/references", json={"asset_id": asset_id})
    return made["id"]


def _write(client, board_id: str, ws: str, item_id: str, kind: str, seen: Seen, **form):
    with mock_patch("app.domain.ai_chat.chat", side_effect=seen.chat), \
            mock_patch("app.domain.boards.actions.look_at", side_effect=seen.look_at):
        return run_on_board_settled(client, board_id, ws, producer="write", item_id=item_id, kind=kind,
                            form={"prompt": "写一段人物小传", **form})


def test_便签认得连进来的资产和_at_到的资产_描述当材料_参考图给模型看() -> None:
    client = fresh_client()
    ws = _workspace(client)
    _writable_profile(client)
    seed_assets(ws, {"a1": "image", "a2": "image", "a3": "image", "b1": "image"})
    linked = _person(client, ws, "林小满", ("a1", "a2", "a3"))
    mentioned = _person(client, ws, "阿澄", ("b1",))
    board_id = _board(client, ws, [
        {"id": "cast", "kind": "entity", "x": 0, "y": 0, "entity_id": linked},
        {"id": "n1", "kind": "note", "x": 400, "y": 0, "text": ""},
    ], [{"id": "e1", "source": "cast", "target": "n1"}])

    seen = Seen("林小满,班长……")
    done = _write(client, board_id, ws, "n1", "note", seen, entity_ids=[mentioned])
    assert done.status_code == 200, done.text
    assert "资产「林小满」(人物)" in seen.text() and "short hair, school uniform" in seen.text()
    assert "资产「阿澄」(人物)" in seen.text(), "正文里 @ 到的也带上"
    assert seen.looked_at == ["a1", "a2", "b1"], "每个资产挑前两张参考图给模型看"
    note = done.json()["canvas"]["items"][1]
    assert (note["text"], note["run"]["status"]) == ("林小满,班长……", "succeeded")


def test_连进来的便签和文档按连线先后当材料_文档给钉住的那一版() -> None:
    client = fresh_client()
    ws = _workspace(client)
    _writable_profile(client)
    note = client.post("/api/notes", json={"workspace_id": ws, "title": "企划", "markdown": "第一版正文\n"}).json()
    edited = client.patch(f"/api/notes/{note['id']}", json={
        "workspace_id": ws, "base_revision": note["revision"], "title": "企划", "markdown": "第二版正文",
    })
    assert edited.status_code == 200, edited.text
    brief = _parsed_document(client, ws, "brief.md", "# 简报\n今天发布。")
    board_id = _board(client, ws, [
        {"id": "plan", "kind": "document", "x": 0, "y": 0, "note_id": note["id"], "note_revision": note["revision"]},
        {"id": "brief", "kind": "document", "x": 0, "y": 200, "asset_id": brief},
        {"id": "memo", "kind": "note", "x": 0, "y": 400, "text": "  便签上的字  "},
        {"id": "blank", "kind": "note", "x": 0, "y": 600, "text": "   "},
        {"id": "n1", "kind": "note", "x": 400, "y": 0, "text": ""},
    ], [
        {"id": "e1", "source": "brief", "target": "n1"},
        {"id": "e2", "source": "memo", "target": "n1"},
        {"id": "e3", "source": "blank", "target": "n1"},
        {"id": "e4", "source": "plan", "target": "n1"},
        {"id": "e5", "source": "memo", "target": "n1"},
    ])

    seen = Seen("写好了")
    done = _write(client, board_id, ws, "n1", "note", seen, prompt="接着往下写")
    assert done.status_code == 200, done.text
    material = str(seen.messages[1]["content"])
    head, _, rest = material.partition("\n\n")
    assert head == "上游给的材料:"
    parts = rest.split("\n\n---\n\n")
    assert len(parts) == 3, "空便签不算一份,同一格连两根线只取一次"
    assert "今天发布。" in parts[0], "按连线的先后"
    assert parts[1:] == ["便签上的字", "第一版正文"], "去掉首尾空白;文档给钉住的那一版,不是最新版"
    assert seen.messages[-1]["content"] == "接着往下写", "要求只是用户写的那句"


def test_连着却读不到的文档_不写() -> None:
    from app.db.models import Job

    client = fresh_client()
    ws = _workspace(client)
    _writable_profile(client)
    board_id = _board(client, ws, [
        {"id": "empty", "kind": "document", "x": 0, "y": 0, "text": "空文档"},
        {"id": "n1", "kind": "note", "x": 400, "y": 0, "text": ""},
    ], [{"id": "e1", "source": "empty", "target": "n1"}])

    seen = Seen("不该写出来")
    done = _write(client, board_id, ws, "n1", "note", seen)
    assert done.status_code == 400, done.text
    assert "空文档" in done.json()["detail"]
    assert seen.messages == [], "没问模型"
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.workspace_id == ws, Job.kind == "board_write").count() == 0, "没起任务"
    cell = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"][1]
    assert "run" not in cell, "这一格没被摆成「正在写」"


def test_空文档格写出一篇新笔记_文档格引用它() -> None:
    client = fresh_client()
    ws = _workspace(client)
    _writable_profile(client)
    board_id = _board(client, ws, [{"id": "doc", "kind": "document", "x": 0, "y": 0}])
    assert client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"][0]["form"] == \
        {"producer": "write"}, "新放下的文档格挂着写字"

    seen = Seen("# 林小满的一天\n\n早上七点……")
    done = _write(client, board_id, ws, "doc", "document", seen)
    assert done.status_code == 200, done.text
    assert "存成一篇笔记" in seen.messages[0]["content"], "文档格的交代和便签不一样:可以用 Markdown 组织"
    assert seen.options["timeout"] >= 180, "看着图写一整篇要两三分钟,不能用缺省的 60 秒(用户撞上过 Gateway 60 秒超时)"
    doc = done.json()["canvas"]["items"][0]
    assert doc["run"]["status"] == "succeeded" and doc["note_revision"] == 1 and doc["text"] == "林小满的一天"
    note = client.get(f"/api/notes/{doc['note_id']}", params={"workspace_id": ws}).json()
    assert note["title"] == "林小满的一天" and note["markdown"].startswith("# 林小满的一天")
    assert note["sources"][0]["kind"] == "board" and note["sources"][0]["id"] == board_id


def test_引用着笔记的文档格_照原文改_写成那篇的新一版() -> None:
    client = fresh_client()
    ws = _workspace(client)
    _writable_profile(client)
    note = client.post("/api/notes", json={"workspace_id": ws, "title": "企划", "markdown": "第一版正文"}).json()
    board_id = _board(client, ws, [{"id": "doc", "kind": "document", "x": 0, "y": 0, "note_id": note["id"],
                                    "note_revision": note["revision"], "text": "企划"}])

    seen = Seen("改过的正文")
    done = _write(client, board_id, ws, "doc", "document", seen, prompt="改短一点")
    assert done.status_code == 200, done.text
    assert "这篇文档现在的内容:\n第一版正文" in seen.text()
    doc = done.json()["canvas"]["items"][0]
    assert (doc["note_id"], doc["note_revision"]) == (note["id"], note["revision"] + 1), "钉到新的那一版"
    latest = client.get(f"/api/notes/{note['id']}", params={"workspace_id": ws}).json()
    assert latest["markdown"] == "改过的正文" and latest["title"] == "企划", "标题等别的都不动"


def test_写的时候被停下_笔记不新建也不改写() -> None:
    """模型写的那一会儿人点了停止:那一格落成已取消,而笔记照样新建了一篇(或把引用着的那篇改成新一版)——
    停下的活儿留下了副作用。落笔记之前查一眼任务还活着没有。"""
    from sqlalchemy import select

    from app.db.models import Job, Note
    from app.domain.jobs import cancel_job

    client = fresh_client()
    ws = _workspace(client)
    _writable_profile(client)
    note = client.post("/api/notes", json={"workspace_id": ws, "title": "企划", "markdown": "第一版正文"}).json()
    board_id = _board(client, ws, [
        {"id": "doc", "kind": "document", "x": 0, "y": 0, "note_id": note["id"], "note_revision": note["revision"], "text": "企划"},
        {"id": "blank", "kind": "document", "x": 0, "y": 300},
    ])

    class StoppedWhileWriting(Seen):
        def chat(self, target, messages, **kwargs):
            with SessionLocal() as db:
                job = db.scalars(select(Job).where(Job.kind == "board_write", Job.status == "running")).one()
                cancel_job(db, job)
                db.commit()
            return super().chat(target, messages, **kwargs)

    for item_id in ("doc", "blank"):
        done = _write(client, board_id, ws, item_id, "document", StoppedWhileWriting("停下之后写出来的"), prompt="改短一点")
        assert done.status_code == 200, done.text
        cell = next(one for one in done.json()["canvas"]["items"] if one["id"] == item_id)
        assert cell["run"]["status"] == "cancelled", cell["run"]

    with SessionLocal() as db:
        notes = db.scalars(select(Note).where(Note.workspace_id == ws)).all()
    assert [one.id for one in notes] == [note["id"]], "停下之后照样新建了一篇笔记"
    latest = client.get(f"/api/notes/{note['id']}", params={"workspace_id": ws}).json()
    assert (latest["revision"], latest["markdown"]) == (note["revision"], "第一版正文"), "停下之后照样改写了引用着的那篇"


def test_老画板上的文档格补上写字() -> None:
    import json

    from sqlalchemy import text

    from app.core.db import engine
    from app.db.migrations import _migrate_board_documents_can_be_written

    client = fresh_client()
    ws = _workspace(client)
    board_id = _board(client, ws, [{"id": "doc", "kind": "document", "x": 0, "y": 0},
                                   {"id": "n", "kind": "note", "x": 0, "y": 300}])
    with engine.begin() as conn:
        raw = conn.execute(text("SELECT canvas, revision FROM boards WHERE id = :id"), {"id": board_id}).one()
        canvas = json.loads(raw[0]) if isinstance(raw[0], str) else raw[0]
        canvas["items"][0].pop("form", None)
        conn.execute(text("UPDATE boards SET canvas = :c WHERE id = :id"), {"c": json.dumps(canvas), "id": board_id})
        before = raw[1]
    _migrate_board_documents_can_be_written()
    with SessionLocal() as db:
        from app.db.models import Board

        board = db.get(Board, board_id)
        assert board.canvas["items"][0]["form"] == {"producer": "write"}
        assert board.revision == before + 1
