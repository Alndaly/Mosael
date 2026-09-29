"""会话分组的用例:按分组所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看分组只要是成员;建、改名、排序、删都要 `ai` —— 和对话、生成会话本身同一道闸。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import SessionGroup, User
from app.domain import session_groups as groups
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def readable(db: Session, user: User, group_id: str) -> SessionGroup:
    """他看得见的那个分组。不存在、不是成员都是 404。"""
    group = db.get(SessionGroup, group_id)
    if group is None:
        raise NotVisible("sessionGroupErr_notFound")
    ensure_workspace_access(db, user, group.workspace_id)
    return group


def editable(db: Session, user: User, group_id: str) -> SessionGroup:
    group = readable(db, user, group_id)
    ensure_workspace_perm(db, user, group.workspace_id, "ai")
    return group


def list_all(db: Session, user: User, workspace_id: str, kind: str) -> list[SessionGroup]:
    ensure_workspace_access(db, user, workspace_id)
    return groups.list_groups(db, workspace_id, kind)


def create(db: Session, user: User, workspace_id: str, *, kind: str, name: str) -> SessionGroup:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return groups.create_group(db, workspace_id=workspace_id, kind=kind, name=name, owner_user_id=user.id)


def update(db: Session, user: User, group_id: str, *, name: str | None, sort_order: int | None) -> SessionGroup:
    """None = 这次不改它。"""
    group = editable(db, user, group_id)
    if name is not None:
        groups.rename_group(db, group, name)
    if sort_order is not None:
        groups.set_group_order(db, group, sort_order)
    return group


def delete(db: Session, user: User, group_id: str) -> None:
    """删掉分组,**里面的会话留着**(退回未分组,见 session_groups.delete_group)。"""
    groups.delete_group(db, editable(db, user, group_id))
