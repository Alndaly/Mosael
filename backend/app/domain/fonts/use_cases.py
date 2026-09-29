"""字幕字体的用例:按字体所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看列表、取字体文件不点名权限;上传、删除点名 `upload`。不提交事务;删文件等提交之后再做。
"""

from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.unit_of_work import after_commit
from app.db.models import Font, User
from app.domain.fonts import delete_font_files, import_uploaded_font
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def _font(db: Session, font_id: str) -> Font:
    font = db.get(Font, font_id)
    if font is None:
        raise NotVisible("Font not found")
    return font


def readable_font(db: Session, user: User, font_id: str) -> Font:
    font = _font(db, font_id)
    ensure_workspace_access(db, user, font.workspace_id)
    return font


def list_fonts(db: Session, user: User, workspace_id: str) -> list[Font]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Font).where(Font.workspace_id == workspace_id).order_by(Font.created_at.desc())
    return list(db.scalars(stmt))


def upload_font(db: Session, user: User, workspace_id: str, upload: UploadFile) -> Font:
    ensure_workspace_perm(db, user, workspace_id, "upload")
    return import_uploaded_font(db, workspace_id=workspace_id, upload=upload)


def delete_font(db: Session, user: User, font_id: str) -> None:
    font = _font(db, font_id)
    ensure_workspace_perm(db, user, font.workspace_id, "upload")
    db.delete(font)
    after_commit(db, lambda: delete_font_files(font))
