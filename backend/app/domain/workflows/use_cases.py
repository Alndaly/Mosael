"""工作流的闸:谁看得见、谁能改哪条工作流、哪些节点(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

取对象顺带过闸(readable / editable),和 permissions.require_asset 同一个形状:接口和智能体工具都从这里拿
工作流,闸不按入口各写一份。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User, Workflow
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.workflows import available_node_types, list_workflows as _list
from app.domain.workflows.node_catalog import describe_node_types


def readable(db: Session, user: User, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise NotVisible("Workflow not found")
    ensure_workspace_access(db, user, workflow.workspace_id)
    return workflow


def editable(db: Session, user: User, workflow_id: str) -> Workflow:
    """他能改的那条工作流(改图、运行、认可、恢复、删除、开编排会话都要 edit)。"""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise NotVisible("Workflow not found")
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    return workflow


def ensure_can_edit(db: Session, user: User, workspace_id: str) -> None:
    """能在这个工作区里建 / 导入工作流。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")


def ensure_can_browse(db: Session, user: User, workspace_id: str) -> None:
    """只读地看这个工作区里的工作流周边(模板的前置检查、字段选项)。"""
    ensure_workspace_access(db, user, workspace_id)


def start_from_page(
    db: Session, user: User, workspace_id: str, *, template_id: str, url: str, profile_id: str | None, locale: str | None,
) -> Workflow:
    """内嵌浏览器顶栏「用当前页开工」(见 workflows/from_page)。

    借的是档案主人的登录态:档案要是这个人用得了的(别人的私有档案被拒,`sharing.NotUsableError`)——
    和工作流运行时开浏览器那一步同一道闸(见 browser.usable_profile),建图时就拦,不留一张注定跑不起来的图。
    """
    from app.domain import browser
    from app.domain.workflows.from_page import start_from_page as prepare

    ensure_workspace_perm(db, user, workspace_id, "edit")
    if profile_id:
        browser.usable_profile(db, workspace_id, profile_id, actor=user.id)
    return prepare(
        db, workspace_id=workspace_id, template_id=template_id, url=url, profile_id=profile_id or None,
        user_id=user.id, locale=locale,
    )


def list_workflows(db: Session, user: User, workspace_id: str) -> list[Workflow]:
    ensure_workspace_access(db, user, workspace_id)
    return _list(db, workspace_id)


def node_types(db: Session, user: User, locale: str) -> list[dict[str, Any]]:
    """这个人能用的节点类型(内置 + 他接的插件),按面板分组排好、按 `locale` 翻好。"""
    return describe_node_types(available_node_types(db, user_id=user.id), locale)


#: 一次最多问多少个类型。一张图里认不出的插件节点就那么几种。
MAX_UNUSABLE_QUERY = 100


def unusable_node_types(db: Session, user: User, types: list[str]) -> list[dict[str, str]]:
    """这些节点类型里他用不了的插件节点,各自为什么(见 plugins.nodes.why_unusable)。按请求方的语言说。"""
    from app.domain.plugins.nodes import why_unusable

    out: list[dict[str, str]] = []
    for node_type in dict.fromkeys(types[:MAX_UNUSABLE_QUERY]):
        reason = why_unusable(db, node_type, user.id)
        if reason is not None:
            out.append({"type": node_type, "reason": str(reason)})
    return out
