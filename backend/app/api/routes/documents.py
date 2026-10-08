"""文档的解析结果(ADR 0031 §2):列出、重新解析、按段读正文、取页面图和插图。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from app.api.responses import file_response

from app.api.deps import CurrentUser, DbSession, Tx
from app.core.i18n import tr
from app.api.schemas import AssetExtractionOut, DocumentNoteOut, DocumentTextOut, DocumentPagesRequest, DocumentParseRequest, ExtractionSectionsOut
from app.db.models import AssetExtraction
from app.domain.capabilities import CapabilityUnavailable
from app.domain.documents import use_cases as documents
from app.domain.documents.extraction import DocumentParseError, extraction_dir, read_sections

router = APIRouter(tags=["documents"])


@router.get("/assets/{asset_id}/extractions", response_model=list[AssetExtractionOut])
def list_extractions(asset_id: str, db: Tx, user: CurrentUser) -> list[AssetExtraction]:
    """这份文档的每一次解析,新的在前。一次都没有过的(升级改回来的那批)在这里补上本地解析 —— 阅读器打开就看到
    「解析中」,而不是一句「还没解析」(见 documents.extraction.ensure_parsed)。"""
    #: 读着读着会**建**一次解析任务,所以是 Tx:任务在这次请求提交之后才开跑(jobs.dispatch_job)。
    return documents.list_extractions(db, user, asset_id)


@router.post("/assets/{asset_id}/extractions", response_model=AssetExtractionOut)
def parse_document(asset_id: str, body: DocumentParseRequest, db: Tx, user: CurrentUser) -> AssetExtraction:
    """(重新)解析一次。`provider_id` 点名用哪一家;不点名按「设置 → 能力提供方 → 文档解析」的默认。"""
    try:
        return documents.parse(db, user, asset_id, body.provider_id)
    except (DocumentParseError, CapabilityUnavailable) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/extractions/{extraction_id}/sections", response_model=ExtractionSectionsOut)
def get_extraction_sections(asset_id: str, extraction_id: str, db: DbSession, user: CurrentUser,
                            first: int = Query(1, ge=1), last: int | None = Query(None, ge=1)) -> dict:
    """第 first–last 段的正文(不给 last 就到最后一段)。读的人按段取 —— 几百页的文档不必一次拿全。"""
    extraction = documents.readable_extraction(db, user, asset_id, extraction_id)
    if extraction.status != "succeeded":
        raise HTTPException(status_code=409, detail=tr("routeErr_extractionNotFinished"))
    return {"total": extraction.sections, "unit": extraction.unit,
            "sections": read_sections(extraction, first, last or extraction.sections)}


@router.get("/assets/{asset_id}/document")
def read_document(asset_id: str, db: DbSession, user: CurrentUser,
                  first: int = Query(1, ge=1), last: int | None = Query(None, ge=1),
                  offset: int = Query(0, ge=0)) -> dict:
    """给智能体读:目录 + 第 first–last 段的正文,从第 first 段的第 offset 个字起(有字数上限,超了 `next`
    说从哪接着读,可能是一段的中间)。还在解析会等一小会儿。"""
    from app.domain.documents.reading import DocumentReadError, read

    asset = documents.readable_document(db, user, asset_id)
    try:
        return read(db, asset.workspace_id, asset.id, first, last, offset)
    except DocumentReadError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/document/text", response_model=DocumentTextOut)
def document_full_text(asset_id: str, db: Tx, user: CurrentUser) -> dict:
    """画板上的文档格:解析出的全文(不带段标记)和解析的状态。连进写作 / 生成格时喂的就是它。"""
    #: 从没解析过的会在这里补一次本地解析(见 document_text),所以是 Tx:提交之后解析任务才开跑。
    from app.domain.documents.extraction import latest_extraction
    from app.domain.documents.reading import document_text

    asset = documents.readable_document(db, user, asset_id)
    text = document_text(db, asset.workspace_id, asset.id)
    latest = latest_extraction(db, asset.id, succeeded=False)
    #: 停下的(cancelled)和失败一样是「这一版没有正文」,不能一直显示「解析中」。
    status = "ready" if text is not None else "failed" if latest is not None and latest.status in ("failed", "cancelled") else "parsing"
    return {"asset_id": asset.id, "title": asset.name.rsplit(".", 1)[0], "markdown": text or "", "status": status,
            "error": latest.error if status == "failed" and latest is not None else ""}


@router.post("/assets/{asset_id}/document/analyze")
def analyze_document(asset_id: str, body: DocumentPagesRequest, db: DbSession, user: CurrentUser) -> dict:
    """那几页的页面图 + 文字交给视觉模型(看版式、图表、截图)。"""
    from app.domain.analysis.service import AnalysisError
    from app.domain.documents.reading import DocumentReadError

    try:
        return documents.analyze(db, user, asset_id, body.pages, body.question, body.profile_id)
    except DocumentReadError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except AnalysisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assets/{asset_id}/note", response_model=DocumentNoteOut)
def save_document_as_note(asset_id: str, db: Tx, user: CurrentUser) -> dict:
    """把最新成功的那份解析存成一篇笔记(插图这时才进素材库)。"""
    try:
        note = documents.save_as_note(db, user, asset_id)
    except DocumentParseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"note_id": note.id, "title": note.title}


@router.get("/assets/{asset_id}/extractions/{extraction_id}/files/{path:path}")
def get_extraction_file(asset_id: str, extraction_id: str, path: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """页面图(pages/…)和插图(images/…)。只认这两个目录下的文件 —— 路径是从 Markdown 里来的,不能让它走出解析目录。"""
    extraction = documents.readable_extraction(db, user, asset_id, extraction_id)
    root = extraction_dir(extraction).resolve()
    target = (root / path).resolve()
    if not (target.is_relative_to(root / "pages") or target.is_relative_to(root / "images")) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return file_response(db, target)
