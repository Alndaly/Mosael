from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from app.domain import ai_retry
from app.domain.usage import billable
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.kb import config as kb_config
from app.domain.providers import resolve_profile

"""
知识库向量层(可选增强):配置 kb_embedding_vendor + kb_embedding_model
即启用。向量存 Milvus —— 默认内嵌 milvus-lite 单文件(零服务),
kb_milvus_uri 指向 http(s) 时用同一套代码连完整 Milvus 服务。
Embedding 走 OpenAI 兼容 /embeddings 端点(复用 AI 供应商配置)。
任何一步失败都只降级(基线 FTS5 不受影响),绝不让保存/检索报错。
"""

logger = logging.getLogger(__name__)

#: 更名前就叫这个,**不要改**:它是 Milvus 里的集合名,现有用户的向量全在里面。
#: 改名等于把他们已建好的知识库索引全部弃掉(检索静默返回空),要动必须配一次重建迁移。
COLLECTION = "mibu_kb_chunks"
_client_lock = threading.Lock()
_client: Any | None = None


def vector_tier_enabled() -> bool:
    return kb_config.get().enabled


class EmbeddingError(RuntimeError):
    pass


def embed_texts(db: Session, texts: list[str], *, user_id: str | None, workspace_id: str = "") -> list[list[float]]:
    """向量化一批文本。**这是全项目唯一的 embedding 出口**,所以记账也放在这里。

    整批记一条:入库一篇文档是几十块文本一次请求,而检索是一句话一次 —— 两者都只该在账上
    留一行。workspace_id 不给就取环境上下文(检索走 HTTP 请求,闸门已经绑好了)。
    """
    cfg = kb_config.get()
    profile = resolve_profile(db, cfg.vendor, cfg.provider_profile_id, user_id=user_id)
    if profile is None:
        raise EmbeddingError("没有可用的嵌入供应商配置,或者你还没在这条连接上填自己的密钥")
    base_url = profile.base_url.rstrip("/")
    try:
        with billable(
            db,
            capability="embedding",
            operation="kb_embed",
            workspace_id=workspace_id,
            provider=profile.vendor or "",
            model=cfg.model,
            provider_profile_id=profile.id,
        ) as call:
            response = ai_retry.post(
                f"{base_url}/embeddings",
                headers={"Authorization": f"Bearer {profile.api_key}"} if profile.api_key else {},
                json={"model": cfg.model, "input": texts},
                timeout=60,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage") or {}
            call.meter(
                input_tokens=int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0),
                texts=len(texts),
                raw=usage if isinstance(usage, dict) else {},
            )
            vectors = [item["embedding"] for item in sorted(payload["data"], key=lambda item: item["index"])]
            if len(vectors) != len(texts):
                raise EmbeddingError("embedding 数量与输入不一致")
            return vectors
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise EmbeddingError(f"embedding 请求失败: {exc}") from exc


def _get_client() -> Any:
    global _client
    with _client_lock:
        if _client is None:
            from pymilvus import MilvusClient

            _client = MilvusClient(settings.kb_milvus_path)
            _ensure_collection(_client)
        return _client


def _ensure_collection(client: Any) -> None:
    if not client.has_collection(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            dimension=kb_config.get().dim,
            primary_field_name="id",
            id_type="string",
            max_length=64,
            vector_field_name="vector",
            metric_type="IP",
            auto_id=False,
        )
    # milvus-lite 重开进程后集合可能是 released 状态,查询前需显式 load(幂等)
    client.load_collection(COLLECTION)


def upsert_document_vectors(
    db: Session, *, workspace_id: str, document_id: str, chunks: list[tuple[str, str]], user_id: str | None
) -> None:
    """chunks: [(chunk_id, text)]。同步调用方需自行放到后台线程。"""
    if not vector_tier_enabled() or not chunks:
        return
    vectors = embed_texts(db, [text for _id, text in chunks], user_id=user_id, workspace_id=workspace_id)
    client = _get_client()
    client.delete(collection_name=COLLECTION, filter=f'document_id == "{document_id}"')
    client.insert(
        collection_name=COLLECTION,
        data=[
            {
                "id": chunk_id,
                "vector": vector,
                "document_id": document_id,
                "workspace_id": workspace_id,
            }
            for (chunk_id, _text), vector in zip(chunks, vectors)
        ],
    )


def delete_document_vectors(document_id: str) -> None:
    if not vector_tier_enabled():
        return
    try:
        _get_client().delete(collection_name=COLLECTION, filter=f'document_id == "{document_id}"')
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB vector delete failed")


def reset_collection() -> None:
    """Drop and recreate the collection empty at the current embedding dim.
    Used when the vector dimension changed — old vectors are no longer valid."""
    client = _get_client()
    try:
        if client.has_collection(COLLECTION):
            client.drop_collection(COLLECTION)
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB drop collection failed")
    _ensure_collection(client)  # recreate at kb_config.get().dim + load


def dense_search(
    db: Session, workspace_id: str, query: str, *, user_id: str | None, limit: int = 20
) -> list[tuple[str, str]]:
    """返回 [(chunk_id, document_id)],按相似度降序;失败返回空(降级)。"""
    if not vector_tier_enabled():
        return []
    try:
        vector = embed_texts(db, [query], user_id=user_id)[0]
        hits = _get_client().search(
            collection_name=COLLECTION,
            data=[vector],
            limit=limit,
            filter=f'workspace_id == "{workspace_id}"',
            output_fields=["document_id"],
        )
        return [(hit["id"], hit["entity"]["document_id"]) for hit in hits[0]]
    except Exception:  # noqa: BLE001 - 降级路径
        logger.exception("KB dense search failed")
        return []
