from __future__ import annotations

import html.parser
import logging
import re
import threading
from typing import Any

import httpx
from sqlalchemy import delete as sa_delete, select, text as sa_text
from sqlalchemy.orm import Session

from app.db.models import KbChunk, KbDocument
from app.domain.kb import graph as kb_graph
from app.domain.kb import vectors as kb_vectors

"""
知识库内核(计划 §6.9,管线借鉴 Revornix:一切转 markdown → 分块 → 检索)。

分层检索,逐级增强:
- 基线:SQLite FTS5 trigram(中文三字子串索引),永远可用、零依赖;
- 向量层:配置 embedding 模型后启用,Milvus(默认内嵌 milvus-lite 单文件,
  可指向完整 Milvus 服务),与 FTS 结果做 RRF 融合;
- 图谱层:配置 Neo4j 后启用,入库抽实体建图,检索用命中文档做种子
  经共享实体扩展相关内容,再融合进结果。
增强层的索引在后台线程跑、失败只降级 —— 保存与检索永不因增强层报错。
"""

logger = logging.getLogger(__name__)
RRF_K = 60

CHUNK_TARGET_CHARS = 500
CHUNK_OVERLAP_CHARS = 60
MIN_FTS_QUERY_CHARS = 3  # trigram 需要 ≥3 字;更短的查询走 LIKE


def chunk_text(text: str, *, target: int = CHUNK_TARGET_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    """按段落聚合到目标长度;超长段落硬切并保留少量重叠。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target * 1.6:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                end = min(len(paragraph), start + target)
                chunks.append(paragraph[start:end])
                if end == len(paragraph):
                    break
                start = end - overlap
            continue
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > target and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _ensure_fts(db: Session) -> None:
    db.execute(
        sa_text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks_fts "
            "USING fts5(text, chunk_id UNINDEXED, document_id UNINDEXED, workspace_id UNINDEXED, tokenize='trigram')"
        )
    )


def reindex_document(db: Session, document: KbDocument) -> int:
    """重建该文档的 chunk 与 FTS 行;返回 chunk 数。增强层索引进后台线程。"""
    _ensure_fts(db)
    db.execute(sa_delete(KbChunk).where(KbChunk.document_id == document.id))
    db.execute(sa_text("DELETE FROM kb_chunks_fts WHERE document_id = :doc"), {"doc": document.id})
    body = f"{document.title}\n\n{document.content}".strip()
    pieces = chunk_text(body)
    chunk_rows: list[tuple[str, str]] = []
    for index, piece in enumerate(pieces):
        chunk = KbChunk(
            workspace_id=document.workspace_id,
            document_id=document.id,
            chunk_index=index,
            text=piece,
        )
        db.add(chunk)
        db.flush()
        chunk_rows.append((chunk.id, piece))
        db.execute(
            sa_text(
                "INSERT INTO kb_chunks_fts (text, chunk_id, document_id, workspace_id) "
                "VALUES (:text, :chunk_id, :document_id, :workspace_id)"
            ),
            {"text": piece, "chunk_id": chunk.id, "document_id": document.id, "workspace_id": document.workspace_id},
        )
    _schedule_enhanced_index(
        workspace_id=document.workspace_id, document_id=document.id, title=document.title, chunks=chunk_rows
    )
    return len(pieces)


def _schedule_enhanced_index(*, workspace_id: str, document_id: str, title: str, chunks: list[tuple[str, str]]) -> None:
    if not (kb_vectors.vector_tier_enabled() or kb_graph.graph_tier_enabled()):
        return

    def run() -> None:
        from app.core.db import SessionLocal

        with SessionLocal() as session:
            try:
                kb_vectors.upsert_document_vectors(
                    session, workspace_id=workspace_id, document_id=document_id, chunks=chunks
                )
            except Exception:  # noqa: BLE001 - 降级
                logger.exception("KB vector indexing failed for %s", document_id)
            try:
                kb_graph.upsert_document_graph(
                    session, workspace_id=workspace_id, document_id=document_id, title=title, chunks=chunks
                )
            except Exception:  # noqa: BLE001 - 降级
                logger.exception("KB graph indexing failed for %s", document_id)

    threading.Thread(target=run, daemon=True).start()


def delete_document(db: Session, document: KbDocument) -> None:
    _ensure_fts(db)
    db.execute(sa_text("DELETE FROM kb_chunks_fts WHERE document_id = :doc"), {"doc": document.id})
    kb_vectors.delete_document_vectors(document.id)
    kb_graph.delete_document_graph(document.id)
    db.delete(document)


def reindex_workspace(db: Session, workspace_id: str) -> int:
    """定时任务「知识库重建」的执行体:全量重建 chunk/FTS。"""
    documents = db.scalars(select(KbDocument).where(KbDocument.workspace_id == workspace_id)).all()
    total = 0
    for document in documents:
        total += reindex_document(db, document)
    return total


def _fts_ranked(db: Session, workspace_id: str, query: str, limit: int) -> list[tuple[str, str]]:
    """FTS5 trigram(bm25 排序),短查询回退 LIKE;返回 [(chunk_id, document_id)]。"""
    rows: list[tuple[str, str]] = []
    if len(query) >= MIN_FTS_QUERY_CHARS:
        fts_query = '"' + query.replace('"', '""') + '"'
        rows = [
            (row[0], row[1])
            for row in db.execute(
                sa_text(
                    "SELECT chunk_id, document_id FROM kb_chunks_fts "
                    "WHERE workspace_id = :ws AND kb_chunks_fts MATCH :q ORDER BY rank LIMIT :limit"
                ),
                {"ws": workspace_id, "q": fts_query, "limit": limit},
            )
        ]
    if not rows:
        rows = [
            (chunk.id, chunk.document_id)
            for chunk in db.scalars(
                select(KbChunk)
                .where(KbChunk.workspace_id == workspace_id, KbChunk.text.like(f"%{query}%"))
                .limit(limit)
            )
        ]
    return rows


def search(db: Session, workspace_id: str, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """混合检索:FTS + 向量(若启用)RRF 融合,再用图谱实体扩展补充;
    每篇文档只留最佳块。任何增强层失败都自动降级为纯 FTS。"""
    cleaned = query.strip()
    if not cleaned:
        return []
    _ensure_fts(db)

    ranked_lists: list[list[tuple[str, str]]] = [_fts_ranked(db, workspace_id, cleaned, limit * 4)]
    dense = kb_vectors.dense_search(db, workspace_id, cleaned, limit=limit * 4)
    if dense:
        ranked_lists.append(dense)

    # RRF 融合(chunk 级):score = Σ 1/(K + rank)
    scores: dict[str, float] = {}
    chunk_doc: dict[str, str] = {}
    for ranked in ranked_lists:
        for rank, (chunk_id, document_id) in enumerate(ranked):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            chunk_doc[chunk_id] = document_id

    # 图谱扩展:用融合后的头部文档做种子,共享实体的相关 chunk 以低权重并入。
    seed_docs: list[str] = []
    for chunk_id in sorted(scores, key=lambda cid: -scores[cid]):
        document_id = chunk_doc[chunk_id]
        if document_id not in seed_docs:
            seed_docs.append(document_id)
        if len(seed_docs) >= 3:
            break
    for rank, (chunk_id, document_id) in enumerate(kb_graph.expand_related_chunks(workspace_id, seed_docs)):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 0.5 / (RRF_K + rank + 1)
        chunk_doc[chunk_id] = document_id

    best_per_doc: dict[str, tuple[str, float]] = {}
    for chunk_id, score in scores.items():
        document_id = chunk_doc[chunk_id]
        current = best_per_doc.get(document_id)
        if current is None or score > current[1]:
            best_per_doc[document_id] = (chunk_id, score)

    ordered_docs = sorted(best_per_doc, key=lambda doc_id: -best_per_doc[doc_id][1])
    results: list[dict[str, Any]] = []
    for document_id in ordered_docs[:limit]:
        chunk_id, score = best_per_doc[document_id]
        chunk = db.get(KbChunk, chunk_id)
        document = db.get(KbDocument, document_id)
        if chunk is None or document is None:
            continue
        results.append(
            {
                "document_id": document.id,
                "title": document.title,
                "source_type": document.source_type,
                "tags": list(document.tags or []),
                "chunk_index": chunk.chunk_index,
                "snippet": chunk.text[:400],
                "score": round(score, 5),
            }
        )
    return results


class _TextExtractor(html.parser.HTMLParser):
    """极简正文提取:丢 script/style/nav,块级标签换行。够用为先,
    未来可换 markitdown/readability 引擎(Revornix 的引擎抽象思路)。"""

    _SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "svg", "iframe"}
    _BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
            return
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        return "\n\n".join(line for line in lines if line)


class KbImportError(RuntimeError):
    pass


def fetch_url_as_text(url: str, *, timeout: float = 20.0) -> tuple[str, str]:
    """抓取网页并抽出 (title, text)。仅支持 http(s)。"""
    if not re.match(r"^https?://", url):
        raise KbImportError("仅支持 http/https 链接")
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "Mibu/1.0"})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise KbImportError(f"抓取失败: {exc}") from exc
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise KbImportError(f"不支持的内容类型: {content_type or '未知'}")
    if "html" not in content_type:
        return url, response.text
    extractor = _TextExtractor()
    extractor.feed(response.text)
    return extractor.title.strip() or url, extractor.text()
