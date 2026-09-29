"""工作流的读用例:谁看得见哪些工作流、哪些节点(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

写(建、改、运行、认可)的闸暂时还在路由里,随后按同一条规矩迁过来(tests/test_use_case_boundaries_ratchet)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User, Workflow
from app.domain.permissions import NotVisible, ensure_workspace_access
from app.domain.workflows import available_node_types, list_workflows as _list
from app.domain.workflows.node_catalog import describe_node_types


def readable(db: Session, user: User, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise NotVisible("Workflow not found")
    ensure_workspace_access(db, user, workflow.workspace_id)
    return workflow


def list_workflows(db: Session, user: User, workspace_id: str) -> list[Workflow]:
    ensure_workspace_access(db, user, workspace_id)
    return _list(db, workspace_id)


def node_types(db: Session, user: User, locale: str) -> list[dict[str, Any]]:
    """这个人能用的节点类型(内置 + 他接的插件),按面板分组排好、按 `locale` 翻好。"""
    return describe_node_types(available_node_types(db, user_id=user.id), locale)
