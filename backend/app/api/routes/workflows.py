from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.i18n import get_current_locale, t
from typing import Any, TYPE_CHECKING

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
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Job, Workflow
from app.domain.workflows import (
    NODE_CATEGORIES,
    NODE_TYPES,
    config_data_type,
    config_editor,
    config_label,
    WorkflowDomainError,
    create_workflow,
    list_workflows,
    update_workflow,
)
from app.domain.plugins.nodes import plugin_node_types
from app.domain.workflows.engine import start_workflow_job

if TYPE_CHECKING:
    from app.db.models import AgentSession

router = APIRouter(tags=["workflows"])


def _with_data_type(key: str, spec: Any) -> Any:
    """把推导出的语义类型贴到字段声明上;推不出来就原样返回。"""
    if not isinstance(spec, dict):
        return spec
    enriched = dict(spec)
    data_type = config_data_type(key, spec)
    if data_type:
        enriched["data_type"] = data_type
    # 界面上叫什么,也随声明一起发 —— 前端此前自己抄了一张表,81 个键只覆盖了 28 个,
    # 剩下的在中文界面上直接露出英文键名。
    label = config_label(key, spec)
    if label:
        enriched["label"] = label
    # 这个字段的值跟着谁走 —— 父字段一换,这里存的旧值就失效了(换了供应商配置,模型还是
    # 上一家的那个)。声明在后端,是因为**插件节点也有这种关系**,前端一张写死的表覆盖不到。
    depends_on = str(spec.get("depends_on") or "").strip()
    if depends_on:
        enriched["depends_on"] = depends_on
    # object 字段用哪种编辑器:一行一对的映射,还是原始 JSON。
    editor = config_editor(key, spec)
    if editor:
        enriched["editor"] = editor
    return enriched


@router.get("/workflows/node-types", response_model=list[WorkflowNodeTypeOut])
def node_types(db: DbSession, user: CurrentUser) -> list[dict]:
    """节点类型清单,**按面板分组顺序排好**。

    排序放在这里而不是前端:分组和顺序是这份注册表自己的性质(NODE_CATEGORIES 就在它旁边)。
    让前端再排一次,等于把同一份知识抄成两份 —— 加一个分组时忘了改另一边,新节点就会静默
    掉进"其它"里,而没有任何东西会报错。
    """
    order = {name: index for index, name in enumerate(NODE_CATEGORIES)}
    # 插件节点跟内置节点走同一条路出去:同样的字段、同样的分组、同样的排序。前端因此不需要
    # 知道"这一项是插件来的" —— 它在画布上就该跟别的节点没有区别。
    registry = {**NODE_TYPES, **plugin_node_types(db, user.id)}
    #: 目录里存 key,**出口才翻** —— 和发布平台目录、TTS 引擎目录同一条(见 core/i18n)。
    #: 语言从 Accept-Language 来,不是从某个全局配置来:这是个多租户、可远程部署的后端,
    #: 没有「服务端语言」这回事。
    locale = get_current_locale()
    items = [
        {
            "type": key,
            "label": t(meta["label"], locale),
            "description": t(meta["description"], locale),
            #: 翻**这里**、排序**在下面按 key** —— 顺序是这份注册表的性质,不该跟着语言变。
            #: 先翻再排的话,order 表拿翻译后的字去查 key,一个都对不上,所有节点静默掉进末尾。
            "category": t(meta.get("category", ""), locale),
            "category_key": meta.get("category", ""),
            # 每个配置字段带上**它装的是什么**(素材/时间线/…)。界面据此决定给不给素材选择器、
            # 画不画缩略图、连线时类型对不对得上 —— 此前这份知识是前端自己抄的一张表,
            # 「素材」节点本身就漏了,而插件节点它永远也覆盖不到。
            "config": {key: _translated_spec(_with_data_type(key, spec), locale) for key, spec in meta["config"].items()},
            "outputs": list(meta["outputs"]),
            "plugin_name": meta.get("plugin_name", ""),
        }
        for key, meta in registry.items()
    ]
    # 组内保持注册表里的声明顺序(sorted 是稳定的)。
    ordered = sorted(items, key=lambda item: order.get(item["category_key"], len(order)))
    for item in ordered:
        item.pop("category_key", None)  # 排序用的,不该出现在响应里
    return ordered


@router.get("/workflows", response_model=list[WorkflowOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Workflow]:
    ensure_workspace_access(db, user, workspace_id)
    return list_workflows(db, workspace_id)


@router.post("/workflows", response_model=WorkflowOut)
def create(body: WorkflowCreate, db: DbSession, user: CurrentUser) -> Workflow:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
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
WORKFLOW_FILE_FORMAT = "mosael-workflow"
LEGACY_WORKFLOW_FILE_FORMAT = "openstudio-workflow"
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
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    data = body.data
    accepted = (WORKFLOW_FILE_FORMAT, LEGACY_WORKFLOW_FILE_FORMAT)
    if data.get("format") not in accepted or not isinstance(data.get("graph"), dict):
        raise HTTPException(status_code=422, detail="不是有效的 Mosael 工作流文件")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version > WORKFLOW_FILE_VERSION:
        raise HTTPException(status_code=422, detail=f"文件版本({version})比当前应用支持的更新,请升级应用后再导入")
    # 导入是最容易被当成「只是拖个文件进来」的入口,但文件里的 graph 原样落库——含 code 节点的
    # 工作流文件就是一份可执行载荷,门禁和手写一张图完全同级。
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
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    changes = body.model_dump(exclude_unset=True)
    try:
        return update_workflow(db, workflow, changes)
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete(workflow_id: str, db: DbSession, user: CurrentUser) -> Response:
    workflow = _get(db, workflow_id)
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    db.delete(workflow)
    db.commit()
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/run", response_model=JobOut)
def run(workflow_id: str, body: WorkflowRunRequest, db: DbSession, user: CurrentUser) -> Job:
    workflow = _get(db, workflow_id)
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    try:
        return start_workflow_job(db, workflow, created_by=user.id, params=body.params)
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
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    from app.domain.workflows.ai_edit import ai_edit_graph

    try:
        graph, summary = ai_edit_graph(
            db,
            instruction=body.instruction,
            graph=body.graph if body.graph is not None else workflow.graph,
            profile_id=body.profile_id,
            workspace_id=workflow.workspace_id,
            workflow_id=workflow.id,
            user_id=user.id,
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
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    from sqlalchemy import select

    from app.domain.agent import host
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

    from app.domain.agent import host

    workflow = _get(db, workflow_id)
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    return host.create_session(
        db,
        workspace_id=workflow.workspace_id,
        origin="workflow",
        external_key=f"workflow:{workflow_id}:{uuid.uuid4().hex[:8]}",
        title="新对话",
    )


def _translated_spec(spec: dict, locale: str) -> dict:
    """翻一个配置字段的说明。

    **有几条说明是现算的**(可用角色、可用生成参数、可用时间线算子)——它们的列表来自各自的
    产地,加一种就该跟着变。所以领域给的是 key + 参数,句子在这里按语言组装:两种语言同时
    跟着那张表走,而不是只有中文那句变。
    """
    out = dict(spec)
    #: label 和 description 都是 key。label 那张表按**键名**登记(selector 在六种浏览器节点里
    #: 是同一个意思),所以翻在这里而不是在表里 —— 表只管「这个键叫什么」。
    if isinstance(out.get("label"), str):
        out["label"] = t(out["label"], locale)
    if isinstance(out.get("description"), str):
        out["description"] = t(out["description"], locale, **(out.get("description_params") or {}))
    #: 参数是给翻译用的,不该出现在响应里(和 core/i18n 的 PARAMS_FIELD 同一个道理)。
    out.pop("description_params", None)
    return out


def _get(db: DbSession, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow
