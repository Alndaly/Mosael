"""「用当前页开工」:内嵌浏览器里正开着一条视频 / 一个账号主页,一键用分析模板把它跑起来。

三张分析模板(见 templates_analysis):视频爆款拆解、评论区洞察要视频链接,账号运营诊断要账号主页链接。
做的事只有一件 —— **把一张模板图准备好**:没建过就按模板建,建过就打开最近改过的那张;开始节点填上当前页的链接,
数据来源选「内嵌浏览器」;有浏览器档案时,读页面那一步(打开浏览器)换成浏览器池里的这个档案、下载视频那一步也借它的
登录态 —— 用户正在这个档案里看着这一页,同一个登录态去读,读到的才是他看到的东西。不替他点运行:跑之前他可能还想
填「我关心什么」。

按节点**类型**改,不按节点 id:用户可能改过图、挪过节点,类型是这几步不变的身份。

绑着定时任务的那张不改:定时任务按图跑,改了链接,它下一次就去分析别的东西了。那时另建一张。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import pick_text
from app.db.models import RecordReference, Workflow
from app.domain.workflows import WorkflowDomainError, create_workflow, edit_workflow_graph, list_workflows
from app.domain.workflows.templates_analysis import (
    ACCOUNT_ANALYSIS,
    ANALYSIS_TEMPLATE_CATALOG,
    BROWSER,
    COMMENT_INSIGHTS,
    VIRAL_VIDEO_BREAKDOWN,
)

#: 能「用当前页开工」的模板 → 链接填进开始节点的哪一格。
PAGE_TEMPLATES: dict[str, str] = {
    VIRAL_VIDEO_BREAKDOWN: "video_link",
    COMMENT_INSIGHTS: "video_link",
    ACCOUNT_ANALYSIS: "account_link",
}


def fill_from_page(graph: dict[str, Any], *, template_id: str, url: str, profile_id: str | None) -> dict[str, Any]:
    """在一份图上填好当前页:开始节点的链接与数据来源;有档案时读页面、下视频都用它。返回新的一份,不改原图。"""
    filled = deepcopy(graph)
    for node in filled.get("nodes") or []:
        config = node.setdefault("config", {})
        if node.get("type") == "start":
            params = config.setdefault("params", {})
            params[PAGE_TEMPLATES[template_id]] = url
            params["data_source"] = BROWSER
        elif profile_id and node.get("type") == "browser_open":
            config["session_mode"] = "pool"
            config["profile_id"] = profile_id
        elif profile_id and node.get("type") == "import_url":
            config["profile_id"] = profile_id
    return filled


def reusable_workflow(db: Session, workspace_id: str, template_id: str) -> Workflow | None:
    """这个模板建过的、最近改过的那张;绑着定时任务的不算(见模块说明)。"""
    bound = set(db.scalars(
        select(RecordReference.target_id).where(
            RecordReference.target_kind == "workflow", RecordReference.source_kind == "scheduled_task",
        )
    ))
    for workflow in list_workflows(db, workspace_id):
        meta = (workflow.graph or {}).get("meta") or {}
        if meta.get("template_id") == template_id and workflow.id not in bound:
            return workflow
    return None


def start_from_page(
    db: Session,
    *,
    workspace_id: str,
    template_id: str,
    url: str,
    profile_id: str | None,
    user_id: str,
    locale: str | None,
) -> Workflow:
    """建好(或打开已建的)那张模板图,填上当前页。档案能不能用由调用方先查(见 workflows.use_cases)。"""
    if template_id not in PAGE_TEMPLATES:
        raise WorkflowDomainError("wfErr_pageTemplate")
    existing = reusable_workflow(db, workspace_id, template_id)
    if existing is not None:
        return edit_workflow_graph(
            db,
            existing,
            lambda current: fill_from_page(current, template_id=template_id, url=url, profile_id=profile_id),
            source="edit",
            created_by=user_id,
        )
    from app.domain.workflows.templates import built_in_template_graph

    graph = built_in_template_graph(db, template_id, user_id=user_id, workspace_id=workspace_id, locale=locale)
    entry = next(one for one in ANALYSIS_TEMPLATE_CATALOG if one["id"] == template_id)
    name = pick_text(entry["name"], locale)
    taken = {one.name for one in list_workflows(db, workspace_id)}
    candidate, counter = name, 2
    while candidate in taken:
        candidate = f"{name} ({counter})"
        counter += 1
    return create_workflow(
        db,
        workspace_id=workspace_id,
        name=candidate,
        graph=fill_from_page(graph, template_id=template_id, url=url, profile_id=profile_id),
        source="template",
        created_by=user_id,
        revision_note=f"template:{template_id}",
    )
