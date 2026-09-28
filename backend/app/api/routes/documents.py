"""文档的解析结果(ADR 0031 §2):列出、重新解析、按段读正文、取页面图和插图。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AssetExtractionOut, DocumentNoteOut, DocumentPagesRequest, DocumentParseRequest, ExtractionSectionsOut
from app.db.models import Asset, AssetExtraction
from app.domain.capabilities import CapabilityUnavailable
from app.domain.documents.extraction import DocumentParseError, extraction_dir, read_sections, start_parse
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm

router = APIRouter(tags=["documents"])


def _document(db, user, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    ensure_workspace_access(db, user, asset.workspace_id)
    return asset


def _extraction(db, user, asset_id: str, extraction_id: str) -> AssetExtraction:
    asset = _document(db, user, asset_id)
    extraction = db.get(AssetExtraction, extraction_id)
    if extraction is None or extraction.asset_id != asset.id:
        raise HTTPException(status_code=404, detail="Extraction not found")
    return extraction


@router.get("/assets/{asset_id}/extractions", response_model=list[AssetExtractionOut])
def list_extractions(asset_id: str, db: DbSession, user: CurrentUser) -> list[AssetExtraction]:
    """这份文档的每一次解析,新的在前。"""
    from sqlalchemy import select

    asset = _document(db, user, asset_id)
    return list(db.scalars(select(AssetExtraction).where(AssetExtraction.asset_id == asset.id)
                           .order_by(AssetExtraction.created_at.desc())))


@router.post("/assets/{asset_id}/extractions", response_model=AssetExtractionOut)
def parse_document(asset_id: str, body: DocumentParseRequest, db: DbSession, user: CurrentUser) -> AssetExtraction:
    """(重新)解析一次。`provider_id` 点名用哪一家;不点名按「设置 → 能力提供方 → 文档解析」的默认。"""
    asset = _document(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "upload")
    try:
        return start_parse(db, asset, owner_user_id=user.id, provider_id=body.provider_id, created_by=user.id)
    except (DocumentParseError, CapabilityUnavailable) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/extractions/{extraction_id}/sections", response_model=ExtractionSectionsOut)
def get_extraction_sections(asset_id: str, extraction_id: str, db: DbSession, user: CurrentUser,
                            first: int = Query(1, ge=1), last: int | None = Query(None, ge=1)) -> dict:
    """第 first–last 段的正文(不给 last 就到最后一段)。读的人按段取 —— 几百页的文档不必一次拿全。"""
    extraction = _extraction(db, user, asset_id, extraction_id)
    if extraction.status != "succeeded":
        raise HTTPException(status_code=409, detail="Extraction not finished")
    return {"total": extraction.sections, "unit": extraction.unit,
            "sections": read_sections(extraction, first, last or extraction.sections)}


@router.get("/assets/{asset_id}/document")
def read_document(asset_id: str, db: DbSession, user: CurrentUser,
                  first: int = Query(1, ge=1), last: int | None = Query(None, ge=1)) -> dict:
    """给智能体读:目录 + 第 first–last 段的正文(有字数上限,超了 `next` 说从哪段接着读)。还在解析会等一小会儿。"""
    from app.domain.documents.reading import DocumentReadError, read

    asset = _document(db, user, asset_id)
    try:
        return read(db, asset.workspace_id, asset.id, first, last)
    except DocumentReadError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/document/analyze")
def analyze_document(asset_id: str, body: DocumentPagesRequest, db: DbSession, user: CurrentUser) -> dict:
    """那几页的页面图 + 文字交给视觉模型(看版式、图表、截图)。"""
    from app.domain.analysis.service import AnalysisError
    from app.domain.documents.reading import DocumentReadError, analyze_pages

    asset = _document(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "ai")
    try:
        return analyze_pages(db, asset.workspace_id, asset.id, body.pages, body.question, user_id=user.id,
                             profile_id=body.profile_id)
    except DocumentReadError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/note", response_model=DocumentNoteOut)
def save_document_as_note(asset_id: str, db: DbSession, user: CurrentUser) -> dict:
    """把最新成功的那份解析存成一篇笔记(插图这时才进素材库)。"""
    from app.domain.documents.to_note import save_as_note

    asset = _document(db, user, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, "edit")
    try:
        note = save_as_note(db, asset)
    except DocumentParseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"note_id": note.id, "title": note.title}


@router.get("/assets/{asset_id}/extractions/{extraction_id}/files/{path:path}")
def get_extraction_file(asset_id: str, extraction_id: str, path: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """页面图(pages/…)和插图(images/…)。只认这两个目录下的文件 —— 路径是从 Markdown 里来的,不能让它走出解析目录。"""
    extraction = _extraction(db, user, asset_id, extraction_id)
    root = extraction_dir(extraction).resolve()
    target = (root / path).resolve()
    if not (target.is_relative_to(root / "pages") or target.is_relative_to(root / "images")) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target)
