from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select, update

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    GenerationCreate,
    GenerationCreateResponse,
    GenerationJobOut,
    GenerationOptionOut,
    GenerationSessionCreate,
    GenerationSessionOut,
    GenerationSessionUpdate,
    PromptOptimizeRequest,
    PromptOptimizeResponse,
)
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import GenerationJob, GenerationSession, Job, ProviderUsageEvent
from app.domain import session_groups, sharing
from app.domain.generation import create_generation_job, generation_options
from app.domain.generation.operations import GenerationDomainError
from app.domain.generation.prompt_optimizer import PromptOptimizeError, optimize_image_prompt
from app.domain.generation.runner import start_generation_thread

router = APIRouter(tags=["generation"])


@router.post("/generation/sessions", response_model=GenerationSessionOut)
def create_generation_session(
    body: GenerationSessionCreate, db: DbSession, user: CurrentUser
) -> GenerationSession:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    title = body.title.strip() or "新生成"
    session = GenerationSession(
        workspace_id=body.workspace_id,
        title=title,
        provider_profile_id=body.provider_profile_id,
        model=body.model,
        kind=body.kind,
    )
    db.add(session)
    db.flush()
    # 生成记录是**他的**私人工作线程 —— 默认不共享给工作区(见 domain/sharing.KINDS)。
    sharing.claim(db, "generation_session", session, user)
    db.commit()
    db.refresh(session)
    return sharing.annotate(db, "generation_session", [session], user, session.workspace_id)[0]


@router.get("/generation/sessions", response_model=list[GenerationSessionOut])
def list_generation_sessions(workspace_id: str, db: DbSession, user: CurrentUser) -> list[GenerationSession]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = (
        select(GenerationSession)
        .where(
            GenerationSession.workspace_id == workspace_id,
            sharing.visible_filter("generation_session", user, workspace_id),
        )
        .order_by(GenerationSession.updated_at.desc())
        .limit(50)
    )
    return sharing.annotate(db, "generation_session", list(db.scalars(stmt)), user, workspace_id)


@router.patch("/generation/sessions/{session_id}", response_model=GenerationSessionOut)
def update_generation_session(
    session_id: str, body: GenerationSessionUpdate, db: DbSession, user: CurrentUser
) -> GenerationSession:
    session = _require_generation_session(db, user, session_id, perm="ai")
    fields = body.model_fields_set
    # 收纳不是活动:这一次只改了 group_id 的话,不该让这条会话显得「刚生成过」—— 列表按
    # updated_at 倒序排,收一次纳就把顺序搅了。和对话那边同一条规则(routes/agent.py)。
    organising_only = fields <= {"group_id"} and body.group_id is not None
    kept_updated_at = session.updated_at
    if "title" in fields and body.title is not None:
        session.title = body.title
    if "group_id" in fields:
        if body.group_id and not session_groups.resolve_member_group(
            db, body.group_id, workspace_id=session.workspace_id, kind="generation"
        ):
            raise HTTPException(status_code=404, detail="分组不存在")
        session.group_id = body.group_id or None
    if "provider_profile_id" in fields:
        session.provider_profile_id = body.provider_profile_id
    if "model" in fields:
        session.model = body.model
    if "kind" in fields:
        session.kind = body.kind
    db.commit()
    if organising_only:
        # **不能只是把 updated_at 赋回原值**:赋成原来的值,SQLAlchemy 的变更检测认为「没改」,
        # 这一列就不进 SET,而 onupdate=now 照常把它顶成现在。必须走显式 UPDATE 写回去。
        db.execute(
            update(GenerationSession).where(GenerationSession.id == session.id).values(updated_at=kept_updated_at)
        )
        db.commit()
    db.refresh(session)
    return session


@router.delete("/generation/sessions/{session_id}", status_code=204)
def delete_generation_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    session = _require_generation_session(db, user, session_id, perm="ai")
    generations = list(db.scalars(select(GenerationJob).where(GenerationJob.session_id == session.id)))
    job_ids = [generation.job_id for generation in generations if generation.job_id]
    db.execute(delete(GenerationJob).where(GenerationJob.session_id == session.id))
    if job_ids:
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    db.execute(delete(GenerationSession).where(GenerationSession.id == session.id))
    db.commit()
    return Response(status_code=204)


@router.get("/generation/options", response_model=list[GenerationOptionOut])
def list_generation_options(db: DbSession, user: CurrentUser, kind: str = "image") -> list[GenerationOptionOut]:
    """能用来生成的 (连接 × 模型)。设置页里加了什么,这里就有什么 —— 同一个来源。"""
    return [GenerationOptionOut(**option) for option in generation_options(db, kind)]


@router.post("/generation/optimize-prompt", response_model=PromptOptimizeResponse)
def optimize_prompt(body: PromptOptimizeRequest, db: DbSession, user: CurrentUser) -> PromptOptimizeResponse:
    """把提示词按目标图像平台(provider/model)的习惯优化。前端「优化」按钮与智能助手技能共用。"""
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    try:
        result = optimize_image_prompt(
            db,
            user_id=user.id,
            raw_prompt=body.prompt,
            provider=body.provider,
            model=body.model,
            profile_id=body.provider_profile_id,
            ui_language=body.language,
        )
    except PromptOptimizeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()  # 优化本身只读,但记了一笔用量;记账跟调用方事务走,得落盘
    return PromptOptimizeResponse(**result)


@router.get("/generation/comfyui/workflows")
def list_comfyui_workflows(db: DbSession, user: CurrentUser, profile_id: str | None = None) -> list[dict]:
    """列出某 ComfyUI 档案实例里保存的工作流,供生成表单下拉。ComfyUI 细节封在 comfyui_client,
    这里只解析档案地址、转发列表。连不上 ComfyUI → 502,前端据此提示。"""
    from app.ai.providers.comfyui.client import ComfyUIClient
    from app.domain.providers import resolve_profile

    from app.domain import provider_models

    profile = resolve_profile(db, "comfyui", profile_id, user_id=user.id)
    base = (profile.base_url if profile is not None else "") or "http://127.0.0.1:8188"
    try:
        workflows = ComfyUIClient(base).list_workflows()
    except Exception as exc:  # noqa: BLE001 — 网络/解析失败都回可读 502
        raise HTTPException(status_code=502, detail=f"连接 ComfyUI 失败({base}):{exc}") from exc
    if profile is None:
        return workflows
    # 设置页里加入并启用过工作流,就只给这些 —— 否则设置页那份清单只是装饰:用户在那里
    # 挑挑拣拣,生成页照样把实例里所有东西铺出来。一条都没配过时给全量(不能因为"还没配"
    # 就让本来能用的功能变成空列表)。
    chosen = {
        model.model_id
        for model in provider_models.list_models(db, profile.id, enabled_only=True)
    }
    if not chosen:
        return workflows
    return [item for item in workflows if item.get("path") in chosen]


@router.get("/generation/comfyui/workflow-params")
def get_comfyui_workflow_params(
    workflow: str, db: DbSession, user: CurrentUser, profile_id: str | None = None
) -> list[dict]:
    """提取某工作流的可调参数(类型/范围/当前值/语义角色),供动态表单渲染。"""
    from app.ai.providers.comfyui.client import ComfyUIClient
    from app.domain.providers import resolve_profile

    profile = resolve_profile(db, "comfyui", profile_id, user_id=user.id)
    base = (profile.base_url if profile is not None else "") or "http://127.0.0.1:8188"
    try:
        return ComfyUIClient(base).fetch_workflow_params(workflow)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"读取 ComfyUI 工作流参数失败({base}):{exc}") from exc


@router.post("/generation/jobs", response_model=GenerationCreateResponse)
def create_generation(body: GenerationCreate, db: DbSession, user: CurrentUser) -> GenerationCreateResponse:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    try:
        generation, job = create_generation_job(db, created_by=user.id, **body.model_dump())
    except GenerationDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    start_generation_thread(generation.id)
    return GenerationCreateResponse(
        generation=GenerationJobOut.model_validate(generation),
        job=job,
    )


@router.get("/generation/jobs", response_model=list[GenerationJobOut])
def list_generation_jobs(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str | None = None,
    session_id: str | None = None,
) -> list[GenerationJob]:
    ensure_workspace_access(db, user, workspace_id)
    # 记录跟着它所属的会话走:私有会话里生成的东西不该在工作区的总列表里露出来 —— 否则「私有」
    # 只挡住了标题,内容还在。不属于任何会话的老记录(session_id 为空)照旧全工作区可见。
    visible_sessions = select(GenerationSession.id).where(
        sharing.visible_filter("generation_session", user, workspace_id)
    )
    stmt = select(GenerationJob).where(
        GenerationJob.workspace_id == workspace_id,
        (GenerationJob.session_id.is_(None)) | (GenerationJob.session_id.in_(visible_sessions)),
    )
    if session_id:
        session = _require_generation_session(db, user, session_id)
        if session.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Not found")
        stmt = stmt.where(GenerationJob.session_id == session_id)
    if kind:
        stmt = stmt.where(GenerationJob.kind == kind)
    # 按记录自身时间排序,不 join jobs:job 被任务中心清掉后(job_id 置空)
    # 记录仍要出现在会话历史里 —— inner join 会把它们整个吞掉。
    stmt = stmt.order_by(GenerationJob.created_at.asc(), GenerationJob.id.asc())
    generations = list(db.scalars(stmt))
    _attach_generation_costs(db, generations)
    return generations


def _attach_generation_costs(db: DbSession, generations: list[GenerationJob]) -> None:
    """把各生成记录的计费(用量事件 source_type=generation_job)贴到瞬态属性上,供 GenerationJobOut 读。
    一条生成可能有多个事件(started/succeeded…):已知费用求和;有事件但都无价则计 unknown。"""
    ids = [g.id for g in generations]
    if not ids:
        return
    events = db.scalars(
        select(ProviderUsageEvent).where(
            ProviderUsageEvent.source_type == "generation_job", ProviderUsageEvent.source_id.in_(ids)
        )
    ).all()
    by_gen: dict[str, list[ProviderUsageEvent]] = {}
    for ev in events:
        by_gen.setdefault(ev.source_id, []).append(ev)
    for gen in generations:
        evs = by_gen.get(gen.id, [])
        known = [e for e in evs if e.cost_micros is not None]
        if known:
            gen.cost_micros = sum(int(e.cost_micros) for e in known)  # type: ignore[attr-defined]
            gen.currency = known[0].currency  # type: ignore[attr-defined]
            gen.cost_confidence = known[0].cost_confidence  # type: ignore[attr-defined]
        elif evs:
            gen.cost_micros = None  # type: ignore[attr-defined]
            gen.currency = evs[0].currency  # type: ignore[attr-defined]
            gen.cost_confidence = "unknown"  # type: ignore[attr-defined]


def _require_generation_session(db: DbSession, user: CurrentUser, session_id: str, *, perm: str | None = None) -> GenerationSession:
    session = db.get(GenerationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Not found")
    if perm is None:
        ensure_workspace_access(db, user, session.workspace_id)
    else:
        ensure_workspace_perm(db, user, session.workspace_id, perm)
    # 看不见还不够:猜到 id 也得用不了,否则「私有」只是列表上的一层遮挡。
    if not sharing.may_use(db, "generation_session", session, user):
        raise HTTPException(status_code=404, detail="Not found")
    return session
