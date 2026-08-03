from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    KbChunkOut,
    KbDatasetCreate,
    KbDatasetOut,
    KbDatasetUpdate,
    KbDocumentCreate,
    KbDocumentOut,
    KbDocumentUpdate,
    KbGraphOut,
    KbRetrievalTestRequest,
    KbSearchResultOut,
    KbStatusOut,
    KbUrlImportRequest,
)
from app.core.config import settings
from app.core.permissions import ensure_workspace_access, ensure_workspace_member
from app.db.models import KbChunk, KbDataset, KbDocument
from app.domain import kb
from app.domain.kb import convert as kb_convert
from app.domain.kb import graph as kb_graph
from app.domain.kb import vectors as kb_vectors

router = APIRouter(tags=["kb"])

MAX_IMPORT_FILE_BYTES = 80 * 1024 * 1024


def _clean_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        value = tag.strip()[:40]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _doc_out(document: KbDocument, *, with_content: bool) -> KbDocumentOut:
    payload = KbDocumentOut.model_validate(document)
    payload.content = document.content if with_content else None
    return payload


def _dataset_out(dataset: KbDataset, *, document_count: int = 0) -> KbDatasetOut:
    payload = KbDatasetOut.model_validate(dataset)
    payload.document_count = document_count
    return payload


def _require_dataset(db: DbSession, user: CurrentUser, dataset_id: str) -> KbDataset:
    dataset = db.get(KbDataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    ensure_workspace_access(db, user, dataset.workspace_id)
    return dataset


def _require_document(db: DbSession, user: CurrentUser, document_id: str) -> KbDocument:
    document = db.get(KbDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    ensure_workspace_access(db, user, document.workspace_id)
    return document


def _create_note_document(
    db: DbSession, dataset: KbDataset, body: KbDocumentCreate, user_id: str | None
) -> KbDocumentOut:
    document = KbDocument(
        workspace_id=dataset.workspace_id,
        dataset_id=dataset.id,
        title=body.title.strip(),
        content=body.content,
        source_type=body.source_type,
        source_ref=body.source_ref,
        tags=_clean_tags(body.tags),
        status="queued",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    _enqueue_ingest(document.id, user_id)
    return _doc_out(document, with_content=True)


# ---------- 知识库(dataset) ----------


@router.get("/kb/datasets", response_model=list[KbDatasetOut])
def list_datasets(workspace_id: str, db: DbSession, user: CurrentUser) -> list[KbDatasetOut]:
    ensure_workspace_access(db, user, workspace_id)
    datasets = db.scalars(
        select(KbDataset).where(KbDataset.workspace_id == workspace_id).order_by(KbDataset.updated_at.desc())
    ).all()
    counts = dict(
        db.execute(
            select(KbDocument.dataset_id, func.count(KbDocument.id))
            .where(KbDocument.workspace_id == workspace_id)
            .group_by(KbDocument.dataset_id)
        ).all()
    )
    return [_dataset_out(dataset, document_count=counts.get(dataset.id, 0)) for dataset in datasets]


@router.post("/kb/datasets", response_model=KbDatasetOut)
def create_dataset(body: KbDatasetCreate, db: DbSession, user: CurrentUser) -> KbDatasetOut:
    ensure_workspace_access(db, user, body.workspace_id)
    dataset = KbDataset(
        workspace_id=body.workspace_id,
        name=body.name.strip(),
        description=body.description.strip(),
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _dataset_out(dataset)


@router.get("/kb/datasets/{dataset_id}", response_model=KbDatasetOut)
def get_dataset(dataset_id: str, db: DbSession, user: CurrentUser) -> KbDatasetOut:
    dataset = _require_dataset(db, user, dataset_id)
    count = db.scalar(select(func.count(KbDocument.id)).where(KbDocument.dataset_id == dataset_id)) or 0
    return _dataset_out(dataset, document_count=count)


@router.patch("/kb/datasets/{dataset_id}", response_model=KbDatasetOut)
def update_dataset(dataset_id: str, body: KbDatasetUpdate, db: DbSession, user: CurrentUser) -> KbDatasetOut:
    dataset = _require_dataset(db, user, dataset_id)
    reindex = False
    if body.name is not None:
        dataset.name = body.name.strip()
    if body.description is not None:
        dataset.description = body.description.strip()
    if body.retrieval_mode is not None:
        dataset.retrieval_mode = body.retrieval_mode
    if body.top_k is not None:
        dataset.top_k = body.top_k
    if body.score_threshold is not None or "score_threshold" in body.model_fields_set:
        dataset.score_threshold = body.score_threshold
    if body.graph_enabled is not None:
        dataset.graph_enabled = body.graph_enabled
    if body.chunk_size is not None and body.chunk_size != dataset.chunk_size:
        dataset.chunk_size = body.chunk_size
        reindex = True
    if body.chunk_overlap is not None and body.chunk_overlap != dataset.chunk_overlap:
        dataset.chunk_overlap = body.chunk_overlap
        reindex = True
    if reindex:
        kb.reindex_dataset(db, dataset, user_id=user.id)
    db.commit()
    db.refresh(dataset)
    count = db.scalar(select(func.count(KbDocument.id)).where(KbDocument.dataset_id == dataset_id)) or 0
    return _dataset_out(dataset, document_count=count)


@router.delete("/kb/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: str, db: DbSession, user: CurrentUser) -> Response:
    dataset = _require_dataset(db, user, dataset_id)
    for document in db.scalars(select(KbDocument).where(KbDocument.dataset_id == dataset_id)):
        kb.delete_document(db, document)
    db.delete(dataset)
    db.commit()
    return Response(status_code=204)


# ---------- 文档(挂在 dataset 下) ----------


def _reindex_now(db: DbSession, document: KbDocument, dataset: KbDataset, user_id: str | None) -> None:
    """就地(同步)重建索引,回填状态/错误。用于编辑/重建这类正文已就绪的快路径。

    `user_id` 是**要这次入库的那个人** —— 嵌入要花他的额度、用他的钥匙(见
    domain/provider_credentials)。后台线程拿不到请求身份,所以它在入队时就被带上。
    """
    document.status = "processing"
    try:
        kb.reindex_document(db, document, dataset, user_id=user_id)
        document.status = "completed"
        document.error = ""
    except Exception as exc:  # noqa: BLE001 - 失败落库,不再 500 死路
        document.status = "error"
        document.error = str(exc)[:800]


def _enqueue_ingest(
    document_id: str, user_id: str | None, *, temp_path: str | None = None, temp_filename: str | None = None
) -> None:
    """后台摄取:抓取(url)/转换(file)/分块/索引,全程更新 status;失败落 error。
    导入接口据此立即返回 queued 文档,不再阻塞在数百秒的 MinerU/抓取上。"""

    def run() -> None:
        from app.core.db import SessionLocal

        try:
            with SessionLocal() as db:
                document = db.get(KbDocument, document_id)
                if document is None:
                    return
                dataset = db.get(KbDataset, document.dataset_id)
                if dataset is None:
                    return
                document.status = "processing"
                db.commit()
                try:
                    if document.source_type == "url" and not (document.content or "").strip():
                        title, textc = kb.fetch_url_as_text(document.source_ref)
                        if not textc.strip():
                            raise ValueError("页面没有可提取的正文")
                        if title.strip():  # 抓到网页标题就用它替换占位的 url 标题
                            document.title = title[:300]
                        document.content = textc[:400_000]
                    elif document.source_type == "file" and temp_path:
                        textc = kb_convert.convert_file_to_markdown(Path(temp_path), temp_filename or "upload")
                        if not textc.strip():
                            raise kb_convert.KbConvertError(f"{temp_filename or '文件'} 没有可提取的文本内容")
                        document.content = textc[:400_000]
                    kb.reindex_document(db, document, dataset, user_id=user_id)
                    document.status = "completed"
                    document.error = ""
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - 失败落库,前端可见可重试
                    db.rollback()
                    document = db.get(KbDocument, document_id)
                    if document is not None:
                        document.status = "error"
                        document.error = str(exc)[:800]
                        db.commit()
        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)

    threading.Thread(target=run, daemon=True).start()


@router.get("/kb/datasets/{dataset_id}/documents", response_model=list[KbDocumentOut])
def list_documents(dataset_id: str, db: DbSession, user: CurrentUser) -> list[KbDocumentOut]:
    _require_dataset(db, user, dataset_id)
    documents = db.scalars(
        select(KbDocument).where(KbDocument.dataset_id == dataset_id).order_by(KbDocument.updated_at.desc())
    ).all()
    return [_doc_out(document, with_content=False) for document in documents]


@router.post("/kb/datasets/{dataset_id}/documents", response_model=KbDocumentOut)
def create_document(dataset_id: str, body: KbDocumentCreate, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    """建笔记文档:立即返回 queued,后台分块/索引。"""
    dataset = _require_dataset(db, user, dataset_id)
    return _create_note_document(db, dataset, body, user.id)


@router.post("/kb/datasets/{dataset_id}/documents/import-url", response_model=KbDocumentOut)
def import_url(dataset_id: str, body: KbUrlImportRequest, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    """导入网页:立即返回 queued,后台抓取正文 + 索引;抓取失败落 status=error。"""
    dataset = _require_dataset(db, user, dataset_id)
    document = KbDocument(
        workspace_id=dataset.workspace_id,
        dataset_id=dataset.id,
        title=body.url[:300],
        content="",
        source_type="url",
        source_ref=body.url,
        status="queued",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    _enqueue_ingest(document.id, user.id)
    return _doc_out(document, with_content=True)


@router.post("/kb/datasets/{dataset_id}/documents/import-file", response_model=KbDocumentOut)
def import_file(
    dataset_id: str,
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> KbDocumentOut:
    """上传文件:同步只做类型/大小校验 + 落盘临时文件,立即返回 queued;
    后台转换(MinerU/markitdown/纯文本)+ 索引,转换失败落 status=error。"""
    dataset = _require_dataset(db, user, dataset_id)
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    supported = kb_convert.TEXT_SUFFIXES | kb_convert.CONVERTIBLE_SUFFIXES | kb_convert.MINERU_SUFFIXES
    if suffix not in supported:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型: {suffix or '未知'}")
    payload = file.file.read(MAX_IMPORT_FILE_BYTES + 1)
    if len(payload) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=422, detail="文件超过 80MB 上限")

    # 转换在后台,临时文件不能随请求销毁 → delete=False,worker 处理完再删。
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(payload)
    handle.flush()
    handle.close()

    document = KbDocument(
        workspace_id=dataset.workspace_id,
        dataset_id=dataset.id,
        title=Path(filename).stem[:300] or filename[:300],
        content="",
        source_type="file",
        source_ref=filename,
        status="queued",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    _enqueue_ingest(document.id, user.id, temp_path=handle.name, temp_filename=filename)
    return _doc_out(document, with_content=True)


@router.get("/kb/documents/{document_id}", response_model=KbDocumentOut)
def get_document(document_id: str, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    document = _require_document(db, user, document_id)
    return _doc_out(document, with_content=True)


@router.patch("/kb/documents/{document_id}", response_model=KbDocumentOut)
def update_document(document_id: str, body: KbDocumentUpdate, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    document = _require_document(db, user, document_id)
    changed_text = False
    if body.title is not None:
        document.title = body.title.strip()
        changed_text = True
    if body.content is not None:
        document.content = body.content
        changed_text = True
    if body.tags is not None:
        document.tags = _clean_tags(body.tags)
    if changed_text:
        dataset = db.get(KbDataset, document.dataset_id)
        if dataset is not None:
            _reindex_now(db, document, dataset, user.id)
    db.commit()
    db.refresh(document)
    return _doc_out(document, with_content=True)


@router.delete("/kb/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: DbSession, user: CurrentUser) -> Response:
    document = _require_document(db, user, document_id)
    kb.delete_document(db, document)
    db.commit()
    return Response(status_code=204)


@router.get("/kb/documents/{document_id}/chunks", response_model=list[KbChunkOut])
def list_chunks(document_id: str, db: DbSession, user: CurrentUser) -> list[KbChunkOut]:
    document = _require_document(db, user, document_id)
    chunks = db.scalars(
        select(KbChunk).where(KbChunk.document_id == document.id).order_by(KbChunk.chunk_index)
    ).all()
    return [KbChunkOut.model_validate(chunk) for chunk in chunks]


@router.post("/kb/documents/{document_id}/reindex", response_model=KbDocumentOut)
def reindex_document(document_id: str, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    document = _require_document(db, user, document_id)
    dataset = db.get(KbDataset, document.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    _reindex_now(db, document, dataset, user.id)
    db.commit()
    db.refresh(document)
    return _doc_out(document, with_content=True)


# ---------- 检索测试 / 搜索 ----------


@router.post("/kb/datasets/{dataset_id}/retrieval-test", response_model=list[KbSearchResultOut])
def retrieval_test(
    dataset_id: str, body: KbRetrievalTestRequest, db: DbSession, user: CurrentUser
) -> list[dict]:
    """召回测试:query → 命中分块 + 分数 + from_graph 标记。top_k/阈值缺省取库设置。
    只读操作(虽是 POST),用成员级校验而非写权限,viewer 也能跑。"""
    dataset = db.get(KbDataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    ensure_workspace_member(db, user, dataset.workspace_id)
    return kb.search(db, dataset, body.query, user_id=user.id, top_k=body.top_k, score_threshold=body.score_threshold)


@router.get("/kb/datasets/{dataset_id}/search", response_model=list[KbSearchResultOut])
def search_dataset(dataset_id: str, q: str, db: DbSession, user: CurrentUser, limit: int = 8) -> list[dict]:
    dataset = _require_dataset(db, user, dataset_id)
    return kb.search(db, dataset, q, user_id=user.id, top_k=max(1, min(50, limit)))


# ---------- 知识图谱可视化 ----------


@router.get("/kb/datasets/{dataset_id}/graph", response_model=KbGraphOut)
def dataset_graph(dataset_id: str, db: DbSession, user: CurrentUser) -> dict:
    """整库知识图谱(文档↔实体二部图),给前端力导向可视化。未配 Neo4j 时 enabled=False。"""
    _require_dataset(db, user, dataset_id)
    doc_ids = list(
        db.scalars(select(KbDocument.id).where(KbDocument.dataset_id == dataset_id))
    )
    return kb_graph.graph_overview(doc_ids)


@router.get("/kb/documents/{document_id}/graph", response_model=KbGraphOut)
def document_graph(document_id: str, db: DbSession, user: CurrentUser) -> dict:
    """单文档子图。"""
    document = _require_document(db, user, document_id)
    return kb_graph.graph_overview([document.id])


@router.get("/kb/status", response_model=KbStatusOut)
def kb_status(user: CurrentUser) -> KbStatusOut:
    return KbStatusOut(
        convert_engine=kb_convert.active_engine(),
        vector_enabled=kb_vectors.vector_tier_enabled(),
        graph_enabled=kb_graph.graph_tier_enabled(),
        embedding_model=settings.kb_embedding_model if kb_vectors.vector_tier_enabled() else "",
    )
