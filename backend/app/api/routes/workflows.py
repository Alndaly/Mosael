from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from mosael_formats import workflow_file
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Tx
from app.core.i18n import get_current_locale, render_message, tr
from typing import TYPE_CHECKING, Annotated

from app.api.schemas import (
    AgentSessionOut,
    JobOut,
    WorkflowAiEditRequest,
    WorkflowAiEditResponse,
    WorkflowCreate,
    WorkflowFieldOptionOut,
    WorkflowTemplateCheckOut,
    WorkflowTemplateOut,
    WorkflowImportRequest,
    WorkflowNodeTypeOut,
    WorkflowOut,
    WorkflowRevisionDetailOut,
    WorkflowRevisionOut,
    WorkflowRunOutputOut,
    WorkflowRunRequest,
    WorkflowUnusableNodeOut,
    WorkflowUpdate,
)
from app.domain.scheduler import stop_tasks_bound_to_workflow
from app.db.models import Job, Workflow, WorkflowRevision
from app.domain.workflows import (
    WorkflowDomainError,
    create_workflow,
    list_workflows,
    update_workflow,
)
from app.domain.job_center import use_cases as job_center
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.graph_upgrade import upgrade_graph
from app.domain.workflows.run_outputs import full_text
from app.domain.workflows.file_export import (
    WORKFLOW_FILE_SUFFIX,
    ascii_file_stem,
    export_payload,
)
from app.domain.workflows import use_cases as workflow_uc
from app.domain.workflows.revisions import (
    WorkflowGraphConflict,
    WorkflowRevisionError,
    attest_revision,
    get_workflow_revision,
    list_workflow_revisions,
    restore_workflow_revision,
    revision_vouchers,
)
from app.domain.workflows.templates import built_in_template_graph

if TYPE_CHECKING:
    from app.db.models import AgentSession

router = APIRouter(tags=["workflows"])


@router.get("/workflows/node-types", response_model=list[WorkflowNodeTypeOut])
def node_types(db: DbSession, user: CurrentUser) -> list[dict]:
    """节点类型清单,**按面板分组顺序排好**、按请求方的语言翻好(见 domain/workflows/node_catalog)。

    插件节点跟内置节点走同一条路出去:同样的字段、同样的分组、同样的排序。前端因此不需要
    知道"这一项是插件来的" —— 它在画布上就该跟别的节点没有区别。

    **这份组装只有一处**(domain/workflows.available_node_types):AI 编排此前自己组了一份
    只有内置节点的,于是模型不知道插件节点存在,而校验又把图里原样留着的插件节点判成未知类型。
    """
    #: 语言从 Accept-Language 来,不是从某个全局配置来:这是个多租户、可远程部署的后端,
    #: 没有「服务端语言」这回事。
    return workflow_uc.node_types(db, user, get_current_locale())


@router.get("/workflows/node-types/unusable", response_model=list[WorkflowUnusableNodeOut])
def unusable_node_types(db: DbSession, user: CurrentUser, types: Annotated[list[str], Query()]) -> list[dict]:
    """图里这些节点类型里,**这个人**用不了的那些插件节点,各自为什么。

    节点面板只列他能用的插件节点(`/workflows/node-types`),于是图里一个用不了的插件节点在画布上只能说
    「未知」—— 可原因有好几种,该去的地方各不相同。编辑器的就绪清单拿图里认不出的那几个类型来问这里。
    用得了的、不是插件节点的不回。
    """
    return workflow_uc.unusable_node_types(db, user, types)


@router.get("/workflows/templates", response_model=list[WorkflowTemplateOut])
def workflow_templates() -> list[dict]:
    """官方模板:叫什么、干什么、分几步、跑之前要备好什么。**按请求方的语言发下去。**

    说明只有一份(domain/workflows/templates.TEMPLATE_CATALOG),应用的模板卡片和官网的模板页
    读的是同一份 —— 此前是三套各写各的。图标留在前端(和节点图标、任务种类同一条规矩)。
    """
    from app.core.i18n import pick_text
    from app.domain.workflows.templates import TEMPLATE_CATALOG, current_template_versions

    locale = get_current_locale()
    versions = current_template_versions()
    return [
        {
            "id": str(template["id"]),
            "name": pick_text(template["name"], locale),
            "description": pick_text(template["summary"], locale),
            "version": versions[str(template["id"])],
            "stages": [pick_text(stage, locale) for stage in _by_locale(template["stages"], locale)],
            "requirements": [
                {"text": pick_text(one["text"], locale), "check": one["check"], "optional": one["optional"],
                 "group": one["group"]}
                for one in template["requires"]
            ],
        }
        for template in TEMPLATE_CATALOG
    ]


@router.get("/workflows/templates/checks", response_model=list[WorkflowTemplateCheckOut])
def workflow_template_checks(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    """模板前置条件里能自动查的那几样,**对这个人、这个工作区**各齐没齐。

    和模板目录分开:目录是静态文案,能缓存五分钟;这个取决于他刚配没配模型、装没装引擎,
    每次打开模板库都该是新的。
    """
    from app.domain.workflows.templates import requirement_statuses

    workflow_uc.ensure_can_browse(db, user, workspace_id)
    statuses = requirement_statuses(db, user_id=user.id, workspace_id=workspace_id)
    return [{"check": check, "status": status} for check, status in statuses.items()]


def _by_locale(value: object, locale: str) -> list:
    """一串按语言分的清单(`{"zh": [...], "en": [...]}`)。"""
    if isinstance(value, dict):
        from app.core.i18n import DEFAULT_LOCALE

        picked = value.get(locale) or value.get(DEFAULT_LOCALE) or next(iter(value.values()), [])
        return list(picked or [])
    return list(value or [])


@router.get("/workflows/field-options", response_model=list[WorkflowFieldOptionOut])
def workflow_field_options(
    source: str,
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    parent: str = "",
    node_type: str = "",
    workflow_id: str = "",
) -> list[dict]:
    """节点字段的动态选项(字段声明里的 `options_from`)。

    `parent` 是它 depends_on 的那个字段的值;`node_type` 是这个字段长在哪种节点上(插件节点的
    包名在类型里);`workflow_id` 是正在编辑的那张图(可调用工作流要把自己排掉)。三样都是
    **上下文**,不是某个来源的专用参数 —— 前端因此不必知道每个来源各要什么。
    """
    from app.domain.workflows.field_options import FieldOptionsError, OptionContext, field_options

    workflow_uc.ensure_can_browse(db, user, workspace_id)
    context = OptionContext(
        workspace_id=workspace_id,
        user_id=user.id,
        parent=parent,
        locale=get_current_locale(),
        node_type=node_type,
        workflow_id=workflow_id,
    )
    try:
        return field_options(db, source, context)
    except FieldOptionsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows", response_model=list[WorkflowOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Workflow]:
    return workflow_uc.list_workflows(db, user, workspace_id)


def _localized(exc: WorkflowDomainError) -> str:
    """按**这次请求**的语言说出工作流的报错。`str(exc)` 是缺省语言那一句(给日志、落库),
    认得出 key 的就按读的人的语言重翻;认不出的是一句现成的话,原样给。"""
    return render_message(exc.key, get_current_locale(), exc.params) if exc.key else str(exc)


@router.post("/workflows", response_model=WorkflowOut)
def create(body: WorkflowCreate, db: Tx, user: CurrentUser) -> Workflow:
    workflow_uc.ensure_can_edit(db, user, body.workspace_id)
    try:
        graph = body.graph
        if body.template_id:
            if graph is not None:
                raise WorkflowDomainError("routeErr_workflowTemplateAndGraph")
            #: 节点名在造图这一刻定语言 —— 图落库之后就是用户的数据(见 templates.built_in_template_graph)。
            graph = built_in_template_graph(
                db, body.template_id, user_id=user.id, workspace_id=body.workspace_id,
                locale=get_current_locale(),
            )
        return create_workflow(
            db,
            workspace_id=body.workspace_id,
            name=body.name,
            description=body.description,
            graph=graph,
            source="template" if body.template_id else "create",
            created_by=user.id,
            revision_note=f"template:{body.template_id}" if body.template_id else "",
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=_localized(exc)) from exc


@router.post("/workflows/{workflow_id}/rebuild-from-template", response_model=WorkflowOut)
def rebuild_from_template(workflow_id: str, db: Tx, user: CurrentUser) -> Workflow:
    """按**现行**官方模板给这张从旧版模板建出来的图重建一张(开始参数、挑过的素材等带过去),旧图原样保留。

    旧版模板建的图不迁移 —— 图一落库就是用户的数据,他可能改过,不替他悄悄改写(见 templates.rebuilt_from_template)。
    """
    from app.domain.workflows.templates import rebuilt_from_template

    workflow = workflow_uc.readable(db, user, workflow_id)
    workflow_uc.ensure_can_edit(db, user, workflow.workspace_id)
    try:
        graph = rebuilt_from_template(
            db, dict(workflow.graph or {}), user_id=user.id, workspace_id=workflow.workspace_id, locale=get_current_locale(),
        )
        template_id = str(graph["meta"]["template_id"])
        name = render_message("wfTemplateRebuiltName", get_current_locale(), {"name": workflow.name})
        existing = {one.name for one in list_workflows(db, workflow.workspace_id)}
        candidate, counter = name, 2
        while candidate in existing:
            candidate = f"{name} ({counter})"
            counter += 1
        return create_workflow(
            db,
            workspace_id=workflow.workspace_id,
            name=candidate,
            description=workflow.description,
            graph=graph,
            source="template",
            created_by=user.id,
            revision_note=f"template:{template_id}",
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=_localized(exc)) from exc


# ---------------- 文件导出/导入 ----------------
# 信封的形状在 domain/workflows/file_export(「发布到社区」发的也是它)。


@router.get("/workflows/{workflow_id}/export")
def export_one(workflow_id: str, db: DbSession, user: CurrentUser) -> Response:
    workflow = workflow_uc.readable(db, user, workflow_id)
    payload = export_payload(workflow)
    # ASCII 兜底文件名 + RFC 5987 UTF-8 全名,中文工作流名两头都不乱码。
    ascii_name = ascii_file_stem(workflow.name)
    utf8_name = quote(f"{workflow.name}{WORKFLOW_FILE_SUFFIX}")
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}{WORKFLOW_FILE_SUFFIX}"; filename*=UTF-8\'\'{utf8_name}'
        },
    )


@router.post("/workflows/import", response_model=WorkflowOut)
def import_one(body: WorkflowImportRequest, db: Tx, user: CurrentUser) -> Workflow:
    workflow_uc.ensure_can_edit(db, user, body.workspace_id)
    try:
        envelope = workflow_file.read_workflow_file(body.data)
    except workflow_file.WorkflowFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    version = envelope.version
    # 导入是最容易被当成「只是拖个文件进来」的入口,但文件里的 graph 原样落库——含 code 节点的
    # 工作流文件就是一份可执行载荷,门禁和手写一张图完全同级。
    name = envelope.name or "导入的工作流"
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
            description=envelope.description,
            #: 老版本导出的文件带着旧形状(代码字段里的 {{…}}、错接成外层数据边的循环 output):先升级,
            #: 和迁移改库里的图是同一份规则(见 domain/workflows/graph_upgrade)。插件数组的旧形状由
            #: create_workflow 的规范化改。
            graph=upgrade_graph(envelope.graph),
            source="import",
            created_by=user.id,
            revision_note=f"file:v{version}",
        )
    except WorkflowDomainError as exc:
        # 未知节点类型(更新版本导出的文件)/结构非法都会在这里给出具体原因
        raise HTTPException(status_code=422, detail=_localized(exc)) from exc


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_one(workflow_id: str, db: DbSession, user: CurrentUser) -> Workflow:
    return workflow_uc.readable(db, user, workflow_id)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def update(workflow_id: str, body: WorkflowUpdate, db: Tx, user: CurrentUser) -> Workflow:
    workflow = workflow_uc.editable(db, user, workflow_id)
    changes = body.model_dump(exclude_unset=True, exclude={"base_graph_hash"})
    try:
        return update_workflow(
            db, workflow, changes, base_graph_hash=body.base_graph_hash, source="edit", created_by=user.id
        )
    except WorkflowGraphConflict as exc:
        db.rollback()
        # 和画板的 409 同一个形状(见 routes/boards):界面据此重载最新那份,而不是只弹一句报错。
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workflow_graph_conflict",
                "base_graph_hash": exc.base_graph_hash,
                "current_graph_hash": exc.current_graph_hash,
                "message": str(exc),
            },
        ) from exc
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=_localized(exc)) from exc


def _with_vouchers(db, rows: list[WorkflowRevision]) -> list[WorkflowRevision]:
    """给修订标上作者名和认可过它的人(非映射属性,只为序列化而挂)。"""
    from app.db.models import User

    for row in rows:
        author = db.get(User, row.created_by) if row.created_by else None
        row.created_by_name = (author.display_name or author.username) if author is not None else ""
        row.attested_by = sorted(revision_vouchers(db, row) - {row.created_by})
    return rows


@router.get("/workflows/{workflow_id}/revisions", response_model=list[WorkflowRevisionOut])
def list_revisions(workflow_id: str, db: DbSession, user: CurrentUser) -> list[WorkflowRevision]:
    workflow = workflow_uc.readable(db, user, workflow_id)
    return _with_vouchers(db, list_workflow_revisions(db, workflow.id))


@router.post("/workflows/{workflow_id}/revisions/{revision}/attest", response_model=WorkflowRevisionOut)
def attest(workflow_id: str, revision: int, db: Tx, user: CurrentUser) -> WorkflowRevision:
    """「认可这一版」:不改图、不增版,只把自己记成这一版的担保人。

    同事改过的一版要借主人的私有发布账号 / 浏览器档案 / 本机文件时,运行会停下来说这一版需要主人
    认可(见 domain/authority)。认可只对**认可的人自己用得了的东西**有用 —— 所以谁能在这里点都
    无妨,门槛和编辑工作流一样;真正的判断在用的那一刻。
    """
    workflow = workflow_uc.editable(db, user, workflow_id)
    try:
        attested = attest_revision(db, workflow, revision, attested_by=user.id)
    except WorkflowRevisionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _with_vouchers(db, [attested])[0]


@router.get("/workflows/{workflow_id}/revisions/{revision}", response_model=WorkflowRevisionDetailOut)
def get_revision(workflow_id: str, revision: int, db: DbSession, user: CurrentUser) -> WorkflowRevision:
    workflow = workflow_uc.readable(db, user, workflow_id)
    item = get_workflow_revision(db, workflow.id, revision)
    if item is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_workflowRevisionNotFound"))
    return _with_vouchers(db, [item])[0]


@router.post("/workflows/{workflow_id}/revisions/{revision}/restore", response_model=WorkflowOut)
def restore_revision(workflow_id: str, revision: int, db: Tx, user: CurrentUser) -> Workflow:
    workflow = workflow_uc.editable(db, user, workflow_id)
    try:
        restore_workflow_revision(db, workflow, revision, created_by=user.id)
    except WorkflowRevisionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return workflow


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete(workflow_id: str, db: Tx, user: CurrentUser) -> Response:
    workflow = workflow_uc.editable(db, user, workflow_id)
    # 绑着它的定时任务**同一个事务里停用** —— 此前删工作流不管它们:任务仍是启用的,到点照样
    # 触发、照样失败,手动的也照样能点「立即运行」。这一步排在路由这层(和 sharing.forget 一样),
    # 因为定时任务依赖工作流、工作流不能反过来认识定时任务(见 tests/test_import_layering.py)。
    stop_tasks_bound_to_workflow(db, workflow)
    db.delete(workflow)
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/run", response_model=JobOut)
def run(workflow_id: str, body: WorkflowRunRequest, db: Tx, user: CurrentUser) -> Job:
    workflow = workflow_uc.editable(db, user, workflow_id)
    try:
        return start_workflow_job(db, workflow, created_by=user.id, params=body.params)
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=_localized(exc)) from exc


@router.get("/workflows/{workflow_id}/runs", response_model=list[JobOut])
def list_runs(workflow_id: str, db: DbSession, user: CurrentUser, limit: int = 50) -> list[Job]:
    """Execution history: the workflow's run jobs, newest first. Per-run node steps come from
    the existing GET /jobs/{job_id}/events (workflow.node.* events)."""
    workflow = workflow_uc.readable(db, user, workflow_id)
    #: **按工作流在库里筛,再取前 N 条。** 此前是先取整个工作区最新的 N 个工作流任务、再在这里
    #: 按 workflow_id 过滤 —— 同一个工作区里别的工作流多跑几次,这个工作流的记录就被挤出前 N 条,
    #: 历史面板随之变空,而它其实跑过很多次。
    return list(db.scalars(
        select(Job)
        .where(
            Job.kind == "workflow",
            Job.workspace_id == workflow.workspace_id,
            Job.payload["workflow_id"].as_string() == workflow_id,
        )
        .order_by(Job.created_at.desc())
        .limit(max(1, min(200, limit)))
    ).all())


@router.get("/workflows/runs/{job_id}/outputs/{node_id}/{key}", response_model=WorkflowRunOutputOut)
def run_output(job_id: str, node_id: str, key: str, db: DbSession, user: CurrentUser) -> dict:
    """某次运行里某个节点某一处被截断的文字的**全文**。事件快照里长文字只留了开头(见 domain/workflows/run_outputs),
    「本次产出」的复制 / 下载来这里取完整的那一份。

    `key` 是事件 `truncated` 里的那个键:从输出名开始的点号路径 —— 顶层的 `text`,嵌在里面的 `results.3.text`
    (列表按下标、对象按键)。"""
    job_center.readable(db, user, job_id)
    value = full_text(db, job_id, node_id, key)
    if value is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_workflowRunOutputNotFound"))
    return {"value": value}


@router.post("/workflows/{workflow_id}/ai-edit", response_model=WorkflowAiEditResponse)
def ai_edit(workflow_id: str, body: WorkflowAiEditRequest, db: DbSession, user: CurrentUser) -> dict:
    workflow = workflow_uc.editable(db, user, workflow_id)
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
        raise HTTPException(status_code=422, detail=_localized(exc)) from exc
    return {"graph": graph, "summary": summary}


@router.post("/workflows/{workflow_id}/agent-session", response_model=AgentSessionOut)
def workflow_agent_session(workflow_id: str, db: DbSession, user: CurrentUser) -> "AgentSession":
    """工作流的默认智能体会话:按 external_key 找回,记忆随会话长期保留。

    一个工作流可以有多个会话(见下面的 list/create)——这个端点始终返回
    「默认会话」(get-or-create),保持老调用方语义不变。
    """
    workflow = workflow_uc.editable(db, user, workflow_id)
    from app.domain.agent import host

    return host.get_or_create_external_session(
        db,
        workspace_id=workflow.workspace_id,
        origin="workflow",
        external_key=f"workflow:{workflow_id}",
        title=f"工作流 · {workflow.name}",
    )


@router.get("/workflows/{workflow_id}/agent-sessions", response_model=list[AgentSessionOut])
def list_workflow_agent_sessions(workflow_id: str, db: DbSession, user: CurrentUser) -> list["AgentSession"]:
    """该工作流的全部智能体会话(默认会话 + 手动新建的),新→旧。"""
    workflow_uc.readable(db, user, workflow_id)
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

    workflow = workflow_uc.editable(db, user, workflow_id)
    return host.create_session(
        db,
        workspace_id=workflow.workspace_id,
        origin="workflow",
        external_key=f"workflow:{workflow_id}:{uuid.uuid4().hex[:8]}",
        title="新对话",
    )
