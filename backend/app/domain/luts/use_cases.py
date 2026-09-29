"""LUT 的用例:按 LUT 所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看列表不点名权限;上传、改名、删除点名 `upload`。不提交事务;删文件等提交之后再做。
"""

from __future__ import annotations

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.unit_of_work import after_commit
from app.db.models import Lut, User
from app.domain.luts import delete_lut_files, import_uploaded_lut
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def editable_lut(db: Session, user: User, lut_id: str) -> Lut:
    lut = db.get(Lut, lut_id)
    if lut is None:
        raise NotVisible("LUT not found")
    ensure_workspace_perm(db, user, lut.workspace_id, "upload")
    return lut


def list_luts(db: Session, user: User, workspace_id: str) -> list[Lut]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Lut).where(Lut.workspace_id == workspace_id).order_by(Lut.created_at.desc())
    return list(db.scalars(stmt))


def upload_lut(db: Session, user: User, workspace_id: str, upload: UploadFile, name: str | None = None) -> Lut:
    ensure_workspace_perm(db, user, workspace_id, "upload")
    return import_uploaded_lut(db, workspace_id=workspace_id, upload=upload, name=name)


def rename_lut(db: Session, user: User, lut_id: str, name: str) -> Lut:
    lut = editable_lut(db, user, lut_id)
    lut.name = name.strip() or lut.name
    db.flush()
    db.refresh(lut)
    return lut


def delete_lut(db: Session, user: User, lut_id: str) -> None:
    lut = editable_lut(db, user, lut_id)
    db.delete(lut)
    after_commit(db, lambda: delete_lut_files(lut))
