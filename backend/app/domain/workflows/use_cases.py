"""工作流的闸:谁看得见、谁能改哪条工作流、哪些节点(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

取对象顺带过闸(readable / editable),和 permissions.require_asset 同一个形状:接口和智能体工具都从这里拿
工作流,闸不按入口各写一份。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Job, User, Workflow
from app.domain import entities as entity_library
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.workflows import available_node_types, entity_drawing, list_workflows as _list
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


def unusable_node_types(db: Session, user: User, types: list[str]) -> list[dict[str, Any]]:
    """这些节点类型里他用不了的插件节点,各自为什么(见 plugins.nodes.unusable)。按请求方的语言说。修法是到某个连接的库里升级的
    (ComfyUI 上那张工作流的表单还是上一版格式)带上 `upgrade` 和那个连接:画布上标「用不了 · 需要升级」,检查器给「去工作流库升级」。"""
    from app.domain.plugins.nodes import unusable

    out: list[dict[str, Any]] = []
    for node_type in dict.fromkeys(types[:MAX_UNUSABLE_QUERY]):
        found = unusable(db, node_type, user.id)
        if found is not None:
            out.append({"type": node_type, "reason": str(found.error), "upgrade": bool(found.upgrade_in),
                        "instance_id": found.upgrade_in})
    return out


def decide_run_approval(
    db: Session, user: User, approval: Any, *, decision: str, note: str = "", via: str = "app"
) -> bool:
    """批一次停在「等人确认」上的运行:**先按工作区写权限放行,再落决定、唤醒那次运行**。

    **两条路共用这一处**(应用内路由、飞书卡片回调):闸不按入口各写一份(见本模块开头那条规矩)。
    批一次运行是改这个工作区里的东西 —— 那次运行会接着往下跑、可能花钱 —— 所以门槛和"运行一次
    工作流"一样是 `edit`(见 editable)。

    返回是不是**我**落的决定(两条路同时点只有一个赢,见 approvals.decide_and_wake)。
    """
    from app.domain.workflows import approvals

    ensure_workspace_perm(db, user, approval.workspace_id, "edit")
    return approvals.decide_and_wake(
        db, approval, decision=decision, user_id=user.id,
        user_name=user.display_name or user.username, note=note, via=via,
    )


def draw_entity(db: Session, user: User, entity_id: str, ability: str, config: dict[str, Any]) -> Job:
    """资产详情页上的「补全多角度 / 生成表情 / 让它说话」:照这个资产的参考图跑那个工作流节点,画成的挂回来。

    付费生成,闸是资产的 `ai` 那一道(和生成页同一道)。说不通的(没图、模型不收参考图、角度都齐了)
    当场抛 WorkflowDomainError,不起任务(见 workflows/entity_drawing)。
    """
    workspace_id = entity_library.entity_workspace(db, entity_id)
    ensure_workspace_perm(db, user, workspace_id, "ai")
    entity = entity_library.get_entity(db, workspace_id, entity_id)
    return entity_drawing.start_drawing(db, entity, ability, config, actor_id=user.id)
