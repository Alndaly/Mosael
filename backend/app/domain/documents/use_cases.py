"""文档解析结果的用例:按文档所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看解析结果、读正文、取页面图不点名权限;重新解析点名 `upload`,交给视觉模型看点名 `ai`,
存成笔记点名 `edit`。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, AssetExtraction, Note, User
from app.domain.documents.extraction import ensure_parsed, start_parse
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def _asset(db: Session, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotVisible("Asset not found")
    return asset


def readable_document(db: Session, user: User, asset_id: str) -> Asset:
    asset = _asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    return asset


def readable_extraction(db: Session, user: User, asset_id: str, extraction_id: str) -> AssetExtraction:
    asset = readable_document(db, user, asset_id)
    extraction = db.get(AssetExtraction, extraction_id)
    if extraction is None or extraction.asset_id != asset.id:
        raise NotVisible("Extraction not found")
    return extraction


def _document_for(db: Session, user: User, asset_id: str, perm: str) -> Asset:
    asset = _asset(db, asset_id)
    ensure_workspace_perm(db, user, asset.workspace_id, perm)
    return asset


def list_extractions(db: Session, user: User, asset_id: str) -> list[AssetExtraction]:
    """新的在前。一次都没有过的(升级改回来的那批)在这里补上本地解析(见 extraction.ensure_parsed)。"""
    asset = readable_document(db, user, asset_id)
    ensure_parsed(db, asset)
    return list(db.scalars(select(AssetExtraction).where(AssetExtraction.asset_id == asset.id)
                           .order_by(AssetExtraction.created_at.desc())))


def parse(db: Session, user: User, asset_id: str, provider_id: str | None) -> AssetExtraction:
    asset = _document_for(db, user, asset_id, "upload")
    return start_parse(db, asset, owner_user_id=user.id, provider_id=provider_id, created_by=user.id)


def analyze(
    db: Session, user: User, asset_id: str, pages: list[int], question: str, profile_id: str | None
) -> dict[str, Any]:
    """那几页的页面图 + 文字交给视觉模型(看版式、图表、截图)。"""
    from app.domain.documents.reading import analyze_pages

    asset = _document_for(db, user, asset_id, "ai")
    return analyze_pages(db, asset.workspace_id, asset.id, pages, question, user_id=user.id, profile_id=profile_id)


def save_as_note(db: Session, user: User, asset_id: str) -> Note:
    from app.domain.documents.to_note import save_as_note as _save

    return _save(db, _document_for(db, user, asset_id, "edit"), actor_id=user.id)


def save_page_as_note(
    db: Session, user: User, workspace_id: str, *, url: str, title: str, html: str, selection: str,
    project_id: str | None = None,
) -> Note:
    """内嵌浏览器顶栏「存成笔记」:整页正文或选中的文字,带着来源(见 documents/web_page)。点名 `edit`,和存文档为笔记一样。"""
    from app.domain import notes
    from app.domain.documents.web_page import page_note_content

    ensure_workspace_perm(db, user, workspace_id, "edit")
    content = page_note_content(url=url, title=title, html=html, selection=selection, project_id=project_id)
    if content is None:
        raise notes.NoteDomainError("pageNoteErr_empty")
    return notes.create_note(db, workspace_id, content, actor=user.id, origin="create")
