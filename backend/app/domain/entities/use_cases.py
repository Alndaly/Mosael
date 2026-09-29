"""资产库(ADR 0027)的用例:每个资产先查它在哪个工作区,再按那个工作区过闸。

闸在这里(见 CONVENTIONS「一次用例一个事务,授权在领域里」):HTTP 路由和智能体工具调同一个函数。
读不点名权限;写点名 edit / delete;照参考图再画几张是付费生成,和生成页同一道 `ai`。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Entity, GenerationSession, Job, User
from app.domain import entities as library
from app.domain import sharing
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm, require_asset


def entity(db: Session, user: User, entity_id: str, *, perm: str | None = None) -> Entity:
    """取资产并过闸:写点名 `perm`,不传就是只读闸。不在 / 看不见都是 404。"""
    workspace_id = library.entity_workspace(db, entity_id)
    if perm is None:
        ensure_workspace_access(db, user, workspace_id)
    else:
        ensure_workspace_perm(db, user, workspace_id, perm)
    return library.get_entity(db, workspace_id, entity_id)


def list_entities(db: Session, user: User, workspace_id: str, **filters: Any) -> list[Entity]:
    ensure_workspace_access(db, user, workspace_id)
    return library.list_entities(db, workspace_id, **filters)


def create(db: Session, user: User, workspace_id: str, **fields: Any) -> Entity:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return library.create_entity(db, workspace_id=workspace_id, actor_id=user.id, **fields)


def update(db: Session, user: User, entity_id: str, **changes: Any) -> Entity:
    return library.update_entity(db, entity(db, user, entity_id, perm="edit"), actor_id=user.id, **changes)


def delete(db: Session, user: User, entity_id: str, *, with_variants: bool = False) -> None:
    """删资产**不删素材**。有变体时要 `with_variants`(界面在确认框里写清有几个变体)。"""
    library.delete_entity(db, entity(db, user, entity_id, perm="delete"), with_variants=with_variants)


def create_variant(db: Session, user: User, entity_id: str, **fields: Any) -> Entity:
    parent = entity(db, user, entity_id, perm="edit")
    return library.create_entity(
        db, workspace_id=parent.workspace_id, kind=parent.kind, parent_id=parent.id, actor_id=user.id, **fields
    )


def dismiss_lost_references(db: Session, user: User, entity_id: str) -> Entity:
    """「少了哪几张参考图」那句提示看过了。"""
    return library.clear_lost_references(db, entity(db, user, entity_id, perm="edit"))


def add_reference(db: Session, user: User, entity_id: str, asset_id: str, role: str, *, cover: bool = False) -> Entity:
    return library.add_reference(db, entity(db, user, entity_id, perm="edit"), asset_id, role, cover=cover)


def reorder_references(db: Session, user: User, entity_id: str, asset_ids: list[str]) -> Entity:
    return library.reorder_references(db, entity(db, user, entity_id, perm="edit"), asset_ids)


def set_reference_role(db: Session, user: User, entity_id: str, asset_id: str, role: str) -> Entity:
    return library.set_reference_role(db, entity(db, user, entity_id, perm="edit"), asset_id, role)


def remove_reference(db: Session, user: User, entity_id: str, asset_id: str) -> Entity:
    """摘掉一张参考图。素材还在素材库里。"""
    return library.remove_reference(db, entity(db, user, entity_id, perm="edit"), asset_id)


def draw(db: Session, user: User, entity_id: str, ability: str, config: dict[str, Any]) -> Job:
    """照这个资产的参考图再画几张,画成的挂回来。说不通的(没图、模型不收参考图、角度都齐了)
    当场抛 WorkflowDomainError,不起任务。"""
    from app.domain.entities.drawing import start_drawing

    return start_drawing(db, entity(db, user, entity_id, perm="ai"), ability, config, actor_id=user.id)


def usage(db: Session, user: User, entity_id: str) -> tuple[Entity, Any]:
    """在哪里用过。生成记录只算他看得见的会话里的(别人私有会话的提示词不外露)。"""
    row = entity(db, user, entity_id)
    visible = select(GenerationSession.id).where(sharing.visible_filter("generation_session", user, row.workspace_id))
    return row, library.entity_usage(db, row, visible_sessions=visible)


def of_asset(db: Session, user: User, asset_id: str) -> list[Any]:
    """这份素材是哪些资产的参考图。"""
    asset: Asset = require_asset(db, user, asset_id)
    return library.entities_of_asset(db, asset)
