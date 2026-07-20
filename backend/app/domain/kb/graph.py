from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
import logging
import re
import threading
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.providers import resolve_profile

"""
知识库图谱层(可选增强,Revornix GraphRAG 的单机裁剪):配置 neo4j_uri
即启用。入库时用 LLM 抽取实体(人物/地点/主题/风格…),写成
(Document)-[:HAS_CHUNK]->(Chunk)-[:MENTIONS]->(Entity) 图;检索时以
FTS/向量命中的文档为种子,经共享实体扩展出相关 chunk,融合进结果。
社区发现等重活不做 —— "种子→实体→扩展"这一步是收益核心。
失败一律降级,不影响基线检索。
"""

logger = logging.getLogger(__name__)

_driver_lock = threading.Lock()
_driver: Any | None = None

ENTITY_PROMPT = (
    "从下面的文本里抽取最多 10 个关键实体(人物、地点、品牌、主题、视觉风格、"
    "拍摄手法等),输出 JSON 数组,每项 {\"name\": 实体名, \"type\": 类型}。"
    "实体名用原文语言、保持简短;不要输出 JSON 以外的任何内容。\n\n文本:\n"
)


def graph_tier_enabled() -> bool:
    return bool(settings.neo4j_uri)


def _get_driver() -> Any:
    global _driver
    with _driver_lock:
        if _driver is None:
            from neo4j import GraphDatabase

            _driver = GraphDatabase.driver(
                settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
            )
        return _driver


# Ingesting a long document means one extraction call per chunk; bounded so a big upload
# does not fire hundreds of concurrent LLM requests at a local model.
_MAX_PARALLEL_EXTRACT = 4


def extract_entities(db: Session, text: str) -> list[dict[str, str]]:
    """LLM 实体抽取;没有可用模型或解析失败返回空。"""
    profile = _entity_profile(db)
    if profile is None:
        return []
    return _extract_with(profile, text)


def _entity_profile(db: Session):
    """The provider used for entity extraction, read on the CALLING thread.

    Resolving it needs the Session, and a Session belongs to one thread — so it is looked up
    once here rather than per chunk inside a worker. That also removes a redundant DB read per
    chunk that the per-chunk version was doing."""
    vendor = settings.kb_embedding_vendor  # 复用同一供应商配置做轻量抽取
    profile = resolve_profile(db, vendor) if vendor else None
    return profile if profile is not None and profile.default_model else None


def _extract_with(profile, text: str) -> list[dict[str, str]]:
    """The network half — no Session, so it is safe to run on a worker thread."""
    try:
        response = httpx.post(
            f"{profile.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {profile.api_key}"},
            json={
                "model": profile.default_model,
                "messages": [{"role": "user", "content": ENTITY_PROMPT + text[:4000]}],
                "temperature": 0,
            },
            timeout=180,  # 本地模型冷启动加载可能超过 60s
        )
        response.raise_for_status()
        content = str(response.json()["choices"][0]["message"]["content"])
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            return []
        entities = json.loads(match.group(0))
        return [
            {"name": str(item["name"]).strip()[:80], "type": str(item.get("type", ""))[:40]}
            for item in entities
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ][:10]
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB entity extraction failed")
        return []


def upsert_document_graph(
    db: Session, *, workspace_id: str, document_id: str, title: str, chunks: list[tuple[str, str]]
) -> None:
    """chunks: [(chunk_id, text)]。每个 chunk 独立抽实体并写图。"""
    if not graph_tier_enabled() or not chunks:
        return
    driver = _get_driver()
    with driver.session() as session:
        session.run("MATCH (c:Chunk {document_id: $doc}) DETACH DELETE c", doc=document_id)
        session.run(
            "MERGE (d:Document {id: $doc}) SET d.title = $title, d.workspace_id = $ws",
            doc=document_id, title=title, ws=workspace_id,
        )
        # One LLM round-trip per chunk, and they do not depend on each other — so extract them
        # all first, concurrently, then write the graph. The writes stay on this thread because
        # a neo4j Session is no more thread-safe than a SQLAlchemy one.
        profile = _entity_profile(db)
        if profile is None:
            per_chunk: list[list[dict[str, str]]] = [[] for _ in chunks]
        elif len(chunks) == 1:
            per_chunk = [_extract_with(profile, chunks[0][1])]
        else:
            with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL_EXTRACT, len(chunks))) as pool:
                per_chunk = list(pool.map(lambda item: _extract_with(profile, item[1]), chunks))

        for (chunk_id, text), entities in zip(chunks, per_chunk):
            session.run(
                "MATCH (d:Document {id: $doc}) "
                "MERGE (c:Chunk {id: $chunk}) SET c.document_id = $doc, c.workspace_id = $ws "
                "MERGE (d)-[:HAS_CHUNK]->(c)",
                doc=document_id, chunk=chunk_id, ws=workspace_id,
            )
            for entity in entities:
                session.run(
                    "MATCH (c:Chunk {id: $chunk}) "
                    "MERGE (e:Entity {name: $name, workspace_id: $ws}) "
                    "ON CREATE SET e.type = $type "
                    "MERGE (c)-[:MENTIONS]->(e)",
                    chunk=chunk_id, name=entity["name"], type=entity["type"], ws=workspace_id,
                )


def delete_document_graph(document_id: str) -> None:
    if not graph_tier_enabled():
        return
    try:
        with _get_driver().session() as session:
            session.run("MATCH (c:Chunk {document_id: $doc}) DETACH DELETE c", doc=document_id)
            session.run("MATCH (d:Document {id: $doc}) DETACH DELETE d", doc=document_id)
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB graph delete failed")


def graph_overview(document_ids: list[str], *, limit: int = 300) -> dict[str, Any]:
    """给可视化用的二部图:文档节点 + 实体节点 + 文档→实体(提及)边,限定在给定文档集内。
    返回 {enabled, nodes, edges};未配 Neo4j 或出错则 enabled=False/空。"""
    if not graph_tier_enabled() or not document_ids:
        return {"enabled": graph_tier_enabled(), "nodes": [], "edges": []}
    try:
        with _get_driver().session() as session:
            records = session.run(
                "MATCH (d:Document)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(e:Entity) "
                "WHERE d.id IN $docs "
                "RETURN d.id AS doc_id, d.title AS doc_title, e.name AS ent_name, "
                "e.type AS ent_type, count(*) AS weight "
                "ORDER BY weight DESC LIMIT $limit",
                docs=document_ids, limit=limit,
            )
            nodes: dict[str, dict[str, Any]] = {}
            edges: list[dict[str, Any]] = []
            for record in records:
                doc_key = f"doc:{record['doc_id']}"
                ent_key = f"ent:{record['ent_name']}"
                nodes[doc_key] = {
                    "id": doc_key,
                    "label": record["doc_title"] or record["doc_id"],
                    "kind": "document",
                    "ref": record["doc_id"],
                }
                nodes[ent_key] = {
                    "id": ent_key,
                    "label": record["ent_name"],
                    "kind": "entity",
                    "entity_type": record["ent_type"] or "",
                }
                edges.append({"source": doc_key, "target": ent_key, "weight": int(record["weight"])})
            return {"enabled": True, "nodes": list(nodes.values()), "edges": edges}
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB graph overview failed")
        return {"enabled": True, "nodes": [], "edges": []}


def expand_related_chunks(workspace_id: str, seed_document_ids: list[str], *, limit: int = 12) -> list[tuple[str, str]]:
    """种子文档 → 共享实体 → 其他文档的相关 chunk;返回 [(chunk_id, document_id)]。"""
    if not graph_tier_enabled() or not seed_document_ids:
        return []
    try:
        with _get_driver().session() as session:
            records = session.run(
                "MATCH (seed:Document)-[:HAS_CHUNK]->(:Chunk)-[:MENTIONS]->(e:Entity) "
                "WHERE seed.id IN $seeds AND e.workspace_id = $ws "
                "MATCH (e)<-[:MENTIONS]-(c:Chunk)<-[:HAS_CHUNK]-(d:Document) "
                "WHERE NOT d.id IN $seeds "
                "RETURN c.id AS chunk_id, d.id AS document_id, count(e) AS shared "
                "ORDER BY shared DESC LIMIT $limit",
                seeds=seed_document_ids, ws=workspace_id, limit=limit,
            )
            return [(record["chunk_id"], record["document_id"]) for record in records]
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB graph expansion failed")
        return []
