"""共享的用例:把「我的东西」放进一个工作区,或者收回来(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

共享是**主人的授权动作**:别人替他做出来的授权不叫授权。所以只认主人 —— 工作区的 admin 也不行,
他管的是工作区里的内容,不是别人的登录态。不提交事务。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User
from app.domain import sharing
from app.domain.permissions import NotVisible, PermissionDenied, ensure_workspace_access


def _owned(db: Session, user: User, kind: str, resource_id: str, workspace_id: str) -> Any:
    model = sharing.model_for(kind)  # 认不出的种类抛 SharingError
    # 先确认他在目标工作区里 —— 不然共享就成了往别人的工作区里塞东西。
    ensure_workspace_access(db, user, workspace_id)
    resource = db.get(model, resource_id)
    if resource is None:
        raise NotVisible("Not found")
    if resource.owner_user_id != user.id:
        raise PermissionDenied("routeErr_onlyOwnerCanShare")
    return resource


def share(db: Session, user: User, kind: str, resource_id: str, workspace_id: str) -> list[str]:
    """共享进去,回这件东西现在共享到的全部工作区。"""
    _owned(db, user, kind, resource_id, workspace_id)
    sharing.share(db, kind, resource_id, workspace_id, user.id)
    db.flush()
    return sharing.shared_workspaces(db, kind, resource_id)


def unshare(db: Session, user: User, kind: str, resource_id: str, workspace_id: str) -> list[str]:
    _owned(db, user, kind, resource_id, workspace_id)
    sharing.unshare(db, kind, resource_id, workspace_id)
    db.flush()
    return sharing.shared_workspaces(db, kind, resource_id)


def shares_of(db: Session, user: User, kind: str, resource_id: str) -> dict[str, Any]:
    """它归谁、共享到了哪些工作区。用不了的和不存在的同一个回答。"""
    resource = db.get(sharing.model_for(kind), resource_id)
    if resource is None or not sharing.may_use(db, kind, resource, user.id):
        raise NotVisible("Not found")
    return {
        "kind": kind,
        "resource_id": resource_id,
        "owner_user_id": resource.owner_user_id,
        "is_mine": resource.owner_user_id == user.id,
        "workspaces": sharing.shared_workspaces(db, kind, resource_id),
    }
