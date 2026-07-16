from __future__ import annotations

from app.domain import kb
from tests.util import fresh_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_kb_note_crud_and_chinese_search() -> None:
    client = fresh_client()
    ws = _workspace(client)

    doc = client.post(
        "/api/kb/documents",
        json={
            "workspace_id": ws,
            "title": "海边旅拍脚本",
            "content": "开场航拍海面。\n\n第二幕:黄昏时分的沙滩慢镜头,旁白介绍目的地。\n\n结尾定格在日落。",
            "tags": ["脚本", "旅拍"],
        },
    ).json()
    assert doc["source_type"] == "note" and doc["tags"] == ["脚本", "旅拍"]

    listed = client.get(f"/api/kb/documents?workspace_id={ws}").json()
    assert len(listed) == 1 and listed[0]["content"] is None  # 列表不带正文

    detail = client.get(f"/api/kb/documents/{doc['id']}").json()
    assert "黄昏时分" in detail["content"]

    # 中文 FTS(trigram):按短语命中
    hits = client.get(f"/api/kb/search?workspace_id={ws}&q=黄昏时分").json()
    assert hits and hits[0]["document_id"] == doc["id"]
    assert "黄昏时分" in hits[0]["snippet"]

    # 两字短查询走 LIKE 回退
    short_hits = client.get(f"/api/kb/search?workspace_id={ws}&q=航拍").json()
    assert short_hits and short_hits[0]["document_id"] == doc["id"]

    # 编辑正文后旧词消失、新词可检索
    client.patch(f"/api/kb/documents/{doc['id']}", json={"content": "全新的城市夜景延时素材清单。"})
    assert client.get(f"/api/kb/search?workspace_id={ws}&q=黄昏时分").json() == []
    assert client.get(f"/api/kb/search?workspace_id={ws}&q=城市夜景").json() != []

    assert client.delete(f"/api/kb/documents/{doc['id']}").status_code == 204
    assert client.get(f"/api/kb/documents?workspace_id={ws}").json() == []
    assert client.get(f"/api/kb/search?workspace_id={ws}&q=城市夜景").json() == []


def test_kb_url_import_uses_extractor(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)

    monkeypatch.setattr(kb, "fetch_url_as_text", lambda url: ("示例文章", "第一段正文。\n\n第二段有关键词穿越机。"))
    doc = client.post("/api/kb/documents/import-url", json={"workspace_id": ws, "url": "https://example.com/a"}).json()
    assert doc["title"] == "示例文章" and doc["source_type"] == "url"
    hits = client.get(f"/api/kb/search?workspace_id={ws}&q=穿越机").json()
    assert hits and hits[0]["document_id"] == doc["id"]


def test_kb_url_import_error_maps_to_422(monkeypatch) -> None:
    client = fresh_client()
    ws = _workspace(client)

    def boom(url: str):
        raise kb.KbImportError("抓取失败: timeout")

    monkeypatch.setattr(kb, "fetch_url_as_text", boom)
    response = client.post("/api/kb/documents/import-url", json={"workspace_id": ws, "url": "https://example.com"})
    assert response.status_code == 422 and "抓取失败" in response.text


def test_chunk_text_paragraphs_and_long_split() -> None:
    text = "\n\n".join(["段落" + str(i) * 40 for i in range(6)])
    chunks = kb.chunk_text(text, target=120, overlap=20)
    assert len(chunks) >= 2
    assert all(len(chunk) <= 220 for chunk in chunks)

    long_paragraph = "字" * 1000
    long_chunks = kb.chunk_text(long_paragraph, target=300, overlap=30)
    assert len(long_chunks) >= 3
    # 相邻块保留重叠
    assert long_chunks[0][-30:] == long_chunks[1][:30]


def test_kb_workspace_scoping() -> None:
    client = fresh_client()
    ws = _workspace(client)
    doc = client.post(
        "/api/kb/documents", json={"workspace_id": ws, "title": "内部资料", "content": "机密内容"}
    ).json()

    from tests.util import second_client

    other = second_client()
    assert other.get(f"/api/kb/documents/{doc['id']}").status_code in (403, 404)
