from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    KbDocumentCreate,
    KbDocumentOut,
    KbDocumentUpdate,
    KbSearchResultOut,
    KbStatusOut,
    KbUrlImportRequest,
)
from app.core.config import settings
from app.core.permissions import ensure_workspace_access
from app.db.models import KbDocument
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


def _out(document: KbDocument, *, with_content: bool) -> KbDocumentOut:
    payload = KbDocumentOut.model_validate(document)
    if not with_content:
        payload.content = None
    else:
        payload.content = document.content
    return payload


def _require_document(db: DbSession, user: CurrentUser, document_id: str) -> KbDocument:
    document = db.get(KbDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_workspace_access(db, user, document.workspace_id)
    return document


@router.get("/kb/documents", response_model=list[KbDocumentOut])
def list_documents(workspace_id: str, db: DbSession, user: CurrentUser) -> list[KbDocumentOut]:
    ensure_workspace_access(db, user, workspace_id)
    documents = db.scalars(
        select(KbDocument).where(KbDocument.workspace_id == workspace_id).order_by(KbDocument.updated_at.desc())
    ).all()
    return [_out(document, with_content=False) for document in documents]


@router.post("/kb/documents", response_model=KbDocumentOut)
def create_document(body: KbDocumentCreate, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    ensure_workspace_access(db, user, body.workspace_id)
    document = KbDocument(
        workspace_id=body.workspace_id,
        title=body.title.strip(),
        content=body.content,
        source_type=body.source_type,
        source_ref=body.source_ref,
        tags=_clean_tags(body.tags),
    )
    db.add(document)
    db.flush()
    kb.reindex_document(db, document)
    db.commit()
    db.refresh(document)
    return _out(document, with_content=True)


@router.post("/kb/documents/import-url", response_model=KbDocumentOut)
def import_url(body: KbUrlImportRequest, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    ensure_workspace_access(db, user, body.workspace_id)
    try:
        title, text = kb.fetch_url_as_text(body.url)
    except kb.KbImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not text.strip():
        raise HTTPException(status_code=422, detail="页面没有可提取的正文")
    document = KbDocument(
        workspace_id=body.workspace_id,
        title=title[:300],
        content=text[:400_000],
        source_type="url",
        source_ref=body.url,
    )
    db.add(document)
    db.flush()
    kb.reindex_document(db, document)
    db.commit()
    db.refresh(document)
    return _out(document, with_content=True)


@router.post("/kb/documents/import-file", response_model=KbDocumentOut)
def import_file(
    db: DbSession,
    user: CurrentUser,
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
) -> KbDocumentOut:
    """上传文件并经转换引擎(MinerU/markitdown/纯文本)转成 markdown 文档。"""
    ensure_workspace_access(db, user, workspace_id)
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    supported = kb_convert.TEXT_SUFFIXES | kb_convert.CONVERTIBLE_SUFFIXES | kb_convert.MINERU_SUFFIXES
    if suffix not in supported:
        raise HTTPException(status_code=422, detail=f"不支持的文件类型: {suffix or '未知'}")
    payload = file.file.read(MAX_IMPORT_FILE_BYTES + 1)
    if len(payload) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(status_code=422, detail="文件超过 80MB 上限")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
        handle.write(payload)
        handle.flush()
        try:
            text = kb_convert.convert_file_to_markdown(Path(handle.name), filename)
        except kb_convert.KbConvertError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not text.strip():
        raise HTTPException(status_code=422, detail="文件没有可提取的文本内容")
    document = KbDocument(
        workspace_id=workspace_id,
        title=Path(filename).stem[:300] or filename[:300],
        content=text[:400_000],
        source_type="file",
        source_ref=filename,
    )
    db.add(document)
    db.flush()
    kb.reindex_document(db, document)
    db.commit()
    db.refresh(document)
    return _out(document, with_content=True)


@router.get("/kb/status", response_model=KbStatusOut)
def kb_status(user: CurrentUser) -> KbStatusOut:
    """各增强层的启用状态,前端用来给出能力提示。"""
    return KbStatusOut(
        convert_engine=kb_convert.active_engine(),
        vector_enabled=kb_vectors.vector_tier_enabled(),
        graph_enabled=kb_graph.graph_tier_enabled(),
        embedding_model=settings.kb_embedding_model if kb_vectors.vector_tier_enabled() else "",
    )


@router.get("/kb/documents/{document_id}", response_model=KbDocumentOut)
def get_document(document_id: str, db: DbSession, user: CurrentUser) -> KbDocumentOut:
    document = _require_document(db, user, document_id)
    return _out(document, with_content=True)


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
        kb.reindex_document(db, document)
    db.commit()
    db.refresh(document)
    return _out(document, with_content=True)


@router.delete("/kb/documents/{document_id}", status_code=204)
def delete_document(document_id: str, db: DbSession, user: CurrentUser) -> Response:
    document = _require_document(db, user, document_id)
    kb.delete_document(db, document)
    db.commit()
    return Response(status_code=204)


@router.get("/kb/search", response_model=list[KbSearchResultOut])
def search_kb(workspace_id: str, q: str, db: DbSession, user: CurrentUser, limit: int = 8) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    return kb.search(db, workspace_id, q, limit=max(1, min(20, limit)))
