from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, ensure_graph_node_privileges
from typing import TYPE_CHECKING

from app.api.schemas import (
    AgentSessionOut,
    JobOut,
    WorkflowAiEditRequest,
    WorkflowAiEditResponse,
    WorkflowCreate,
    WorkflowImportRequest,
    WorkflowNodeTypeOut,
    WorkflowOut,
    WorkflowRunRequest,
    WorkflowUpdate,
)
from app.core.permissions import ensure_workspace_access
from app.db.models import Job, Workflow
from app.domain.workflows import (
    NODE_TYPES,
    WorkflowDomainError,
    create_workflow,
    list_workflows,
    update_workflow,
)
from app.domain.workflows.engine import start_workflow_job

if TYPE_CHECKING:
    from app.db.models import AgentSession

router = APIRouter(tags=["workflows"])


@router.get("/workflows/node-types", response_model=list[WorkflowNodeTypeOut])
def node_types() -> list[dict]:
    return [
        {
            "type": key,
            "label": meta["label"],
            "description": meta["description"],
            "category": meta.get("category", ""),
            "config": meta["config"],
            "outputs": list(meta["outputs"]),
        }
        for key, meta in NODE_TYPES.items()
    ]


@router.get("/workflows", response_model=list[WorkflowOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Workflow]:
    ensure_workspace_access(db, user, workspace_id)
    return list_workflows(db, workspace_id)


@router.post("/workflows", response_model=WorkflowOut)
def create(body: WorkflowCreate, db: DbSession, user: CurrentUser) -> Workflow:
    ensure_workspace_access(db, user, body.workspace_id)
    ensure_graph_node_privileges(db, user, body.graph)
    try:
        return create_workflow(
            db, workspace_id=body.workspace_id, name=body.name, description=body.description, graph=body.graph
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------- 文件导出/导入 ----------------
# 信封格式:{format, version, name, description, graph}。graph 原样携带 —— 节点里
# 引用的工作区资源(素材/序列/供应商档案等)跨工作区导入后可能悬空,这与「保存放行、
# 就绪检查提示、运行时拦截」的既有分层一致,导入不做资源级校验。
WORKFLOW_FILE_FORMAT = "openstudio-workflow"
#: 更名前导出的文件带的是旧标识。导出一律写新名,导入两者都收——这个字符串已经躺在用户
#: 磁盘上的 .json 里了,只认新名等于让他们此前导出的工作流全部打不开。
LEGACY_WORKFLOW_FILE_FORMATS = ("mibu-workflow",)
WORKFLOW_FILE_VERSION = 1
WORKFLOW_FILE_SUFFIX = f".{WORKFLOW_FILE_FORMAT}.json"


@router.get("/workflows/{workflow_id}/export")
def export_one(workflow_id: str, db: DbSession, user: CurrentUser) -> Response:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    payload = {
        "format": WORKFLOW_FILE_FORMAT,
        "version": WORKFLOW_FILE_VERSION,
        "name": workflow.name,
        "description": workflow.description,
        "graph": workflow.graph,
    }
    # ASCII 兜底文件名 + RFC 5987 UTF-8 全名,中文工作流名两头都不乱码。
    ascii_name = "".join(ch if ch.isascii() and ch not in '\\/:*?"<>|' else "_" for ch in workflow.name) or "workflow"
    utf8_name = quote(f"{workflow.name}{WORKFLOW_FILE_SUFFIX}")
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}{WORKFLOW_FILE_SUFFIX}"; filename*=UTF-8\'\'{utf8_name}'
        },
    )


@router.post("/workflows/import", response_model=WorkflowOut)
def import_one(body: WorkflowImportRequest, db: DbSession, user: CurrentUser) -> Workflow:
    ensure_workspace_access(db, user, body.workspace_id)
    data = body.data
    accepted = (WORKFLOW_FILE_FORMAT, *LEGACY_WORKFLOW_FILE_FORMATS)
    if data.get("format") not in accepted or not isinstance(data.get("graph"), dict):
        raise HTTPException(status_code=422, detail="不是有效的 Open Studio 工作流文件")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version > WORKFLOW_FILE_VERSION:
        raise HTTPException(status_code=422, detail=f"文件版本({version})比当前应用支持的更新,请升级应用后再导入")
    # 导入是最容易被当成「只是拖个文件进来」的入口,但文件里的 graph 原样落库——含 code 节点的
    # 工作流文件就是一份可执行载荷,门禁和手写一张图完全同级。
    ensure_graph_node_privileges(db, user, data["graph"])
    name = str(data.get("name") or "").strip()[:180] or "导入的工作流"
    # 同名冲突自动加序号,导入不打断
    existing = {w.name for w in list_workflows(db, body.workspace_id)}
    candidate, counter = name, 2
    while candidate in existing:
        candidate = f"{name} ({counter})"
        counter += 1
    try:
        return create_workflow(
            db,
            workspace_id=body.workspace_id,
            name=candidate,
            description=str(data.get("description") or "")[:2000],
            graph=data["graph"],
        )
    except WorkflowDomainError as exc:
        # 未知节点类型(更新版本导出的文件)/结构非法都会在这里给出具体原因
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_one(workflow_id: str, db: DbSession, user: CurrentUser) -> Workflow:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    return workflow


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def update(workflow_id: str, body: WorkflowUpdate, db: DbSession, user: CurrentUser) -> Workflow:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    changes = body.model_dump(exclude_unset=True)
    if "graph" in changes:
        ensure_graph_node_privileges(db, user, changes["graph"])
    try:
        return update_workflow(db, workflow, changes)
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete(workflow_id: str, db: DbSession, user: CurrentUser) -> Response:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    db.delete(workflow)
    db.commit()
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/run", response_model=JobOut)
def run(workflow_id: str, body: WorkflowRunRequest, db: DbSession, user: CurrentUser) -> Job:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    try:
        return start_workflow_job(db, workflow, params=body.params)
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/runs", response_model=list[JobOut])
def list_runs(workflow_id: str, db: DbSession, user: CurrentUser, limit: int = 50) -> list[Job]:
    """Execution history: the workflow's run jobs, newest first. Per-run node steps come from
    the existing GET /jobs/{job_id}/events (workflow.node.* events)."""
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    jobs = db.scalars(
        select(Job)
        .where(Job.kind == "workflow", Job.workspace_id == workflow.workspace_id)
        .order_by(Job.created_at.desc())
        .limit(max(1, min(200, limit)))
    ).all()
    return [job for job in jobs if (job.payload or {}).get("workflow_id") == workflow_id]


@router.post("/workflows/{workflow_id}/ai-edit", response_model=WorkflowAiEditResponse)
def ai_edit(workflow_id: str, body: WorkflowAiEditRequest, db: DbSession, user: CurrentUser) -> dict:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    from app.domain.workflows.ai_edit import ai_edit_graph

    try:
        graph, summary = ai_edit_graph(
            db,
            instruction=body.instruction,
            graph=body.graph if body.graph is not None else workflow.graph,
            profile_id=body.profile_id,
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"graph": graph, "summary": summary}


@router.post("/workflows/{workflow_id}/agent-session", response_model=AgentSessionOut)
def workflow_agent_session(workflow_id: str, db: DbSession, user: CurrentUser) -> "AgentSession":
    """工作流的默认智能体会话:按 external_key 找回,记忆随会话长期保留。

    一个工作流可以有多个会话(见下面的 list/create)——这个端点始终返回
    「默认会话」(get-or-create),保持老调用方语义不变。
    """
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    from sqlalchemy import select

    from app.ai.agent import host
    from app.db.models import AgentSession

    key = f"workflow:{workflow_id}"
    existing = db.scalar(select(AgentSession).where(AgentSession.external_key == key))
    if existing is not None:
        return existing
    return host.create_session(
        db,
        workspace_id=workflow.workspace_id,
        origin="workflow",
        external_key=key,
        title=f"工作流 · {workflow.name}",
    )


@router.get("/workflows/{workflow_id}/agent-sessions", response_model=list[AgentSessionOut])
def list_workflow_agent_sessions(workflow_id: str, db: DbSession, user: CurrentUser) -> list["AgentSession"]:
    """该工作流的全部智能体会话(默认会话 + 手动新建的),新→旧。"""
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    from sqlalchemy import or_, select

    from app.db.models import AgentSession

    key = f"workflow:{workflow_id}"
    return list(
        db.scalars(
            select(AgentSession)
            .where(or_(AgentSession.external_key == key, AgentSession.external_key.like(f"{key}:%")))
            .order_by(AgentSession.updated_at.desc())
        )
    )


@router.post("/workflows/{workflow_id}/agent-sessions", response_model=AgentSessionOut)
def create_workflow_agent_session(workflow_id: str, db: DbSession, user: CurrentUser) -> "AgentSession":
    """给工作流再开一个会话(external_key 带唯一后缀,与默认会话同前缀便于归组)。"""
    import uuid

    from app.ai.agent import host

    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    return host.create_session(
        db,
        workspace_id=workflow.workspace_id,
        origin="workflow",
        external_key=f"workflow:{workflow_id}:{uuid.uuid4().hex[:8]}",
        title="新对话",
    )


def _get(db: DbSession, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow
