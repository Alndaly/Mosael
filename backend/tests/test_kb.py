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


def test_kb_file_import_txt_and_md(tmp_path) -> None:
    client = fresh_client()
    ws = _workspace(client)
    doc = client.post(
        "/api/kb/documents/import-file",
        data={"workspace_id": ws},
        files={"file": ("拍摄清单.md", "# 清单\n\n无人机镜头三组。".encode(), "text/markdown")},
    ).json()
    assert doc["title"] == "拍摄清单" and doc["source_type"] == "file"
    hits = client.get(f"/api/kb/search?workspace_id={ws}&q=无人机镜头").json()
    assert hits and hits[0]["document_id"] == doc["id"]


def test_kb_file_import_rejects_unknown_type() -> None:
    client = fresh_client()
    ws = _workspace(client)
    response = client.post(
        "/api/kb/documents/import-file",
        data={"workspace_id": ws},
        files={"file": ("movie.mp4", b"\x00\x01", "video/mp4")},
    )
    assert response.status_code == 422


def test_kb_convert_engine_selection(monkeypatch) -> None:
    from app.core.config import settings
    from app.domain.kb import convert

    monkeypatch.setattr(settings, "kb_convert_engine", "auto")
    monkeypatch.setattr(settings, "mineru_api_token", "")
    assert convert.active_engine() == "markitdown"
    monkeypatch.setattr(settings, "mineru_api_token", "tok")
    assert convert.active_engine() == "mineru"
    monkeypatch.setattr(settings, "kb_convert_engine", "text")
    assert convert.active_engine() == "text"


def test_kb_status_endpoint() -> None:
    client = fresh_client()
    status = client.get("/api/kb/status").json()
    assert status["convert_engine"] in ("markitdown", "mineru", "text")
    assert status["vector_enabled"] is False  # 未配置 embedding 时向量层关闭
    assert status["graph_enabled"] is False


def test_kb_hybrid_rrf_fusion_with_fake_dense(monkeypatch) -> None:
    """向量层命中的文档要能被 RRF 提到前面(用假 dense 结果验证融合逻辑)。"""
    client = fresh_client()
    ws = _workspace(client)
    doc_a = client.post(
        "/api/kb/documents", json={"workspace_id": ws, "title": "文档A", "content": "海边的镜头语言与调色参考。"}
    ).json()
    doc_b = client.post(
        "/api/kb/documents", json={"workspace_id": ws, "title": "文档B", "content": "海边的旅拍脚本与分镜。"}
    ).json()

    from app.core.db import SessionLocal
    from app.db.models import KbChunk
    from app.domain import kb as kb_domain
    from sqlalchemy import select

    with SessionLocal() as session:
        chunk_b = session.scalars(select(KbChunk).where(KbChunk.document_id == doc_b["id"])).first()
        chunk_b_id = chunk_b.id

    # 假向量层:强烈偏向文档B
    monkeypatch.setattr(kb_domain.kb_vectors, "dense_search", lambda db, ws_, q, limit=20: [(chunk_b_id, doc_b["id"])] * 1)

    hits = client.get(f"/api/kb/search?workspace_id={ws}&q=海边").json()
    assert [h["document_id"] for h in hits][0] == doc_b["id"]
    assert {h["document_id"] for h in hits} == {doc_a["id"], doc_b["id"]}


def test_kb_milvus_lite_roundtrip(tmp_path, monkeypatch) -> None:
    """真实 milvus-lite:建库、写入、按 workspace 过滤检索、删除。"""
    from app.core.config import settings
    from app.domain.kb import vectors

    monkeypatch.setattr(settings, "kb_embedding_vendor", "openai-compatible")
    monkeypatch.setattr(settings, "kb_embedding_model", "fake-embed")
    monkeypatch.setattr(settings, "kb_embedding_dim", 8)
    monkeypatch.setattr(settings, "kb_milvus_uri", str(tmp_path / "vec.db"))
    monkeypatch.setattr(vectors, "_client", None)

    def fake_embed(db, texts):
        return [[float(len(t) % 7 == i) for i in range(8)] for t in texts]

    monkeypatch.setattr(vectors, "embed_texts", fake_embed)

    vectors.upsert_document_vectors(None, workspace_id="ws1", document_id="d1", chunks=[("c1", "abc"), ("c2", "abcdefgh")])
    hits = vectors.dense_search(None, "ws1", "abc", limit=5)
    assert hits and hits[0][1] == "d1"
    assert vectors.dense_search(None, "ws-other", "abc", limit=5) == []
    vectors.delete_document_vectors("d1")
    assert vectors.dense_search(None, "ws1", "abc", limit=5) == []
    monkeypatch.setattr(vectors, "_client", None)


def test_kb_graph_expansion_merges_related_docs(monkeypatch) -> None:
    """图谱层扩展出的低权重相关文档要出现在结果尾部(不喧宾夺主)。"""
    client = fresh_client()
    ws = _workspace(client)
    doc_hit = client.post(
        "/api/kb/documents", json={"workspace_id": ws, "title": "命中文档", "content": "冲浪板评测与海浪运镜。"}
    ).json()
    doc_related = client.post(
        "/api/kb/documents", json={"workspace_id": ws, "title": "相关文档", "content": "装备清单:防水壳、脚绳。"}
    ).json()

    from app.core.db import SessionLocal
    from app.db.models import KbChunk
    from app.domain import kb as kb_domain
    from sqlalchemy import select

    with SessionLocal() as session:
        related_chunk = session.scalars(select(KbChunk).where(KbChunk.document_id == doc_related["id"])).first()
        related_id = related_chunk.id

    monkeypatch.setattr(
        kb_domain.kb_graph,
        "expand_related_chunks",
        lambda ws_, seeds, limit=12: [(related_id, doc_related["id"])] if doc_hit["id"] in seeds else [],
    )

    hits = client.get(f"/api/kb/search?workspace_id={ws}&q=冲浪板").json()
    ids = [h["document_id"] for h in hits]
    assert ids[0] == doc_hit["id"]          # 直接命中排最前
    assert doc_related["id"] in ids          # 图谱扩展的相关文档并入结果
