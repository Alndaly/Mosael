"""智能体读文档(ADR 0031 §4):挂进对话的文档短的整篇进上下文、长的给目录;read_document 按段读、有预算;
analyze_document_pages 把那几页的页面图和文字交给视觉模型。"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.domain.documents import office, reading
from tests.document_samples import pdf_bytes, pptx_bytes
from tests.util import fresh_client


@pytest.fixture(autouse=True)
def no_libreoffice(monkeypatch):
    monkeypatch.setattr(office, "find_soffice", lambda: None)


def _import(client, ws: str, name: str, data: bytes) -> str:
    made = client.post("/api/assets/import", data={"workspace_id": ws}, files={"file": (name, data, "application/octet-stream")}).json()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        listed = client.get(f"/api/assets/{made['id']}/extractions").json()
        if listed and listed[0]["status"] in ("succeeded", "failed"):
            return made["id"]
        time.sleep(0.1)
    raise AssertionError("解析一直没结束")


def _markdown(sections: int, words: int) -> bytes:
    return "\n\n".join(f"# 第{i}章\n" + "字" * words for i in range(1, sections + 1)).encode()


def test_按段读_预算用完说从哪段接着读(monkeypatch) -> None:
    monkeypatch.setattr(reading, "READ_BUDGET_CHARS", 250)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = _import(client, ws, "长文.md", _markdown(4, 100))
    first = client.get(f"/api/assets/{asset}/document").json()
    assert first["total"] == 4 and first["unit"] == "section"
    assert [one["title"] for one in first["outline"]] == ["第1章", "第2章", "第3章", "第4章"]
    assert [one["index"] for one in first["sections"]] == [1, 2] and first["next"] == 3
    rest = client.get(f"/api/assets/{asset}/document", params={"first": 3}).json()
    assert [one["index"] for one in rest["sections"]] == [3, 4] and rest["next"] is None


def test_挂进对话的文档_短的整篇_长的给目录(monkeypatch) -> None:
    from app.domain.agent.prompt import user_prompt

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    short = _import(client, ws, "短.md", "# 要点\n今天发布。".encode())
    long = _import(client, ws, "长.md", _markdown(3, 100))
    monkeypatch.setattr(reading, "INLINE_CHARS", 200)
    message = (f"看看这两份 [附件 asset_id={short} 名称=短.md 类型=document] "
               f"[附件 asset_id={long} 名称=长.md 类型=document]")
    with SessionLocal() as db:
        prompt = user_prompt(message, {}, db=db, workspace_id=ws)
    assert "今天发布。" in prompt, "短的整篇放进来"
    assert "共 3 章" in prompt and "1. 第1章" in prompt and "read_document" in prompt
    assert "字" * 100 not in prompt, "长的只放目录"
    assert prompt.endswith(message), "用户那句话原样在最后"


def test_看页面_页面图和文字一起交给视觉模型(monkeypatch) -> None:
    from app.domain.analysis import service

    seen: list[list[dict]] = []
    monkeypatch.setattr(service, "select_analysis_connection", lambda db, profile_id, user_id: object())
    monkeypatch.setattr(service, "call_vision_model", lambda db, profile, messages, call: seen.append(messages) or "第二页是预算表")
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = _import(client, ws, "brief.pdf", pdf_bytes(["Cover page here", "Budget table here"]))
    answer = client.post(f"/api/assets/{asset}/document/analyze", json={"pages": [2, 2, 9], "question": "第二页有什么"})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"asset_id": asset, "pages": [2], "answer": "第二页是预算表"}
    content = seen[0][0]["content"]
    assert "Budget table here" in content[0]["text"] and "第二页有什么" in content[0]["text"]
    assert [one["type"] for one in content[1:]] == ["image_url"]
    assert client.post(f"/api/assets/{asset}/document/analyze", json={"pages": [9]}).status_code == 409


def test_没有页面图的文档说清楚要装_LibreOffice() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = _import(client, ws, "deck.pptx", pptx_bytes([("A", ["a"], "")]))
    refused = client.post(f"/api/assets/{asset}/document/analyze", json={"pages": [1]})
    assert refused.status_code == 409 and "LibreOffice" in refused.json()["detail"]


def test_不是文档_或者别的工作区的_不给读() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    assert client.get("/api/assets/nope/document").status_code == 404
    other = client.post("/api/workspaces", json={"name": "别处"}).json()["id"]
    asset = _import(client, other, "a.md", b"# x")
    with SessionLocal() as db, pytest.raises(reading.DocumentReadError):
        reading.read(db, ws, asset)


# ── 工作流节点「文档转 Markdown」 ───────────────────────────────────────────


def _scope(ws: str):
    from app.domain.boards.tools import BoardScope

    return BoardScope(workspace_id=ws, id="test", name="测试")


def test_工作流节点_读解析出的正文_可以只取几段() -> None:
    from app.domain.workflows.executors import get_executor

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = _import(client, ws, "deck.pptx", pptx_bytes([("开场", ["欢迎"], ""), ("结尾", ["谢谢"], "")]))
    run = get_executor("document_to_markdown")
    with SessionLocal() as db:
        whole = run(db, _scope(ws), {"asset_id": asset})
    assert whole["total"] == 2 and whole["unit"] == "slide" and whole["title"] == "deck"
    assert "# 开场" in whole["markdown"] and "\n\n---\n\n# 结尾" in whole["markdown"]
    assert [one["title"] for one in whole["sections"]] == ["开场", "结尾"]
    with SessionLocal() as db:
        tail = run(db, _scope(ws), {"asset_id": asset, "first": 2})
    assert [one["index"] for one in tail["sections"]] == [2] and "开场" not in tail["markdown"]


def test_工作流节点_还没解析过的先在本机解析一遍() -> None:
    from app.db.models import AssetExtraction
    from app.domain.workflows.executors import get_executor

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = _import(client, ws, "a.md", "# 标题\n正文".encode())
    with SessionLocal() as db:
        db.query(AssetExtraction).delete()
        db.commit()
    with SessionLocal() as db:
        out = get_executor("document_to_markdown")(db, _scope(ws), {"asset_id": asset})
    assert "正文" in out["markdown"]


def test_工作流节点_不是文档的说清楚() -> None:
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors import get_executor
    from tests.util import make_video_asset

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    video = make_video_asset(client, ws)["id"]
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as raised:
        get_executor("document_to_markdown")(db, _scope(ws), {"asset_id": video})
    assert raised.value.key == "wfErr_notDocument"


# ── 画板上的文档格引用文档素材 ──────────────────────────────────────────────


def test_画板_文档格引用文档素材_存得下_种类不对或和笔记同时写都拒(monkeypatch) -> None:
    from tests.util import board_revision, make_video_asset

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    doc = _import(client, ws, "brief.md", "# 简报\n今天发布。".encode())
    video = make_video_asset(client, ws)["id"]
    board = client.post("/api/boards", json={"workspace_id": ws, "name": "B"}).json()["id"]

    def save(items):
        return client.patch(f"/api/boards/{board}", json={"workspace_id": ws, "base_revision": board_revision(client, board, ws),
                                                          "canvas": {"items": items, "edges": []}})

    saved = save([{"id": "d", "kind": "document", "x": 0, "y": 0, "asset_id": doc}])
    assert saved.status_code == 200, saved.text
    cell = saved.json()["canvas"]["items"][0]
    assert cell["asset_id"] == doc and "form" not in cell, "引用文档素材的是只读来源,不挂写字的产出者"
    assert save([{"id": "v", "kind": "document", "x": 0, "y": 0, "asset_id": video}]).status_code == 400
    both = save([{"id": "b", "kind": "document", "x": 0, "y": 0, "asset_id": doc, "note_id": "n", "note_revision": 1}])
    assert both.status_code == 400, both.text

    text = client.get(f"/api/assets/{doc}/document/text").json()
    assert text["status"] == "ready" and text["title"] == "brief" and "今天发布。" in text["markdown"]


def test_画板_节点从文档格取文字_取到的是解析出的全文() -> None:
    from app.domain.boards.tools import _value_of

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    doc = _import(client, ws, "brief.md", "# 简报\n今天发布。".encode())
    with SessionLocal() as db:
        value = _value_of(db, ws, {"id": "d", "kind": "document", "asset_id": doc}, "text", ["note", "document"])
        elsewhere = _value_of(db, "other-ws", {"id": "d", "kind": "document", "asset_id": doc}, "text", ["note", "document"])
    assert value is not None and "今天发布。" in value
    assert elsewhere is None, "别的工作区的文档读不到"
