from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    GenerationCreate,
    GenerationCreateResponse,
    GenerationJobOut,
    GenerationModelOut,
    GenerationSessionCreate,
    GenerationSessionOut,
    GenerationSessionUpdate,
)
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm
from app.ai.providers import get_provider
from app.db.models import GenerationJob, GenerationModel, GenerationSession, Job, ProviderUsageEvent
from app.domain.generation import create_generation_job, ensure_builtin_generation_models
from app.domain.generation.operations import GenerationDomainError
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
    db.commit()
    db.refresh(session)
    return session


@router.get("/generation/sessions", response_model=list[GenerationSessionOut])
def list_generation_sessions(workspace_id: str, db: DbSession, user: CurrentUser) -> list[GenerationSession]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = (
        select(GenerationSession)
        .where(GenerationSession.workspace_id == workspace_id)
        .order_by(GenerationSession.updated_at.desc())
        .limit(50)
    )
    return list(db.scalars(stmt))


@router.patch("/generation/sessions/{session_id}", response_model=GenerationSessionOut)
def update_generation_session(
    session_id: str, body: GenerationSessionUpdate, db: DbSession, user: CurrentUser
) -> GenerationSession:
    session = _require_generation_session(db, user, session_id)
    fields = body.model_fields_set
    if "title" in fields and body.title is not None:
        session.title = body.title
    if "provider_profile_id" in fields:
        session.provider_profile_id = body.provider_profile_id
    if "model" in fields:
        session.model = body.model
    if "kind" in fields:
        session.kind = body.kind
    db.commit()
    db.refresh(session)
    return session


@router.delete("/generation/sessions/{session_id}", status_code=204)
def delete_generation_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    session = _require_generation_session(db, user, session_id)
    generations = list(db.scalars(select(GenerationJob).where(GenerationJob.session_id == session.id)))
    job_ids = [generation.job_id for generation in generations if generation.job_id]
    db.execute(delete(GenerationJob).where(GenerationJob.session_id == session.id))
    if job_ids:
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    db.execute(delete(GenerationSession).where(GenerationSession.id == session.id))
    db.commit()
    return Response(status_code=204)


@router.get("/generation/models", response_model=list[GenerationModelOut])
def list_generation_models(db: DbSession, kind: str | None = None) -> list[GenerationModelOut]:
    ensure_builtin_generation_models(db)
    stmt = select(GenerationModel).where(GenerationModel.enabled.is_(True))
    if kind:
        stmt = stmt.where(GenerationModel.kind == kind)
    stmt = stmt.order_by(GenerationModel.provider, GenerationModel.model)
    return [_generation_model_out(model) for model in db.scalars(stmt)]


@router.get("/generation/comfyui/workflows")
def list_comfyui_workflows(db: DbSession, user: CurrentUser, profile_id: str | None = None) -> list[dict]:
    """列出某 ComfyUI 档案实例里保存的工作流,供生成表单下拉。ComfyUI 细节封在 comfyui_client,
    这里只解析档案地址、转发列表。连不上 ComfyUI → 502,前端据此提示。"""
    from app.ai.providers.comfyui_client import ComfyUIClient
    from app.domain.providers import resolve_profile

    profile = resolve_profile(db, "comfyui", profile_id)
    base = (profile.base_url if profile is not None else "") or "http://127.0.0.1:8188"
    try:
        return ComfyUIClient(base).list_workflows()
    except Exception as exc:  # noqa: BLE001 — 网络/解析失败都回可读 502
        raise HTTPException(status_code=502, detail=f"连接 ComfyUI 失败({base}):{exc}") from exc


@router.get("/generation/comfyui/workflow-params")
def get_comfyui_workflow_params(
    workflow: str, db: DbSession, user: CurrentUser, profile_id: str | None = None
) -> list[dict]:
    """提取某工作流的可调参数(类型/范围/当前值/语义角色),供动态表单渲染。"""
    from app.ai.providers.comfyui_client import ComfyUIClient
    from app.domain.providers import resolve_profile

    profile = resolve_profile(db, "comfyui", profile_id)
    base = (profile.base_url if profile is not None else "") or "http://127.0.0.1:8188"
    try:
        return ComfyUIClient(base).fetch_workflow_params(workflow)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"读取 ComfyUI 工作流参数失败({base}):{exc}") from exc


@router.post("/generation/jobs", response_model=GenerationCreateResponse)
def create_generation(body: GenerationCreate, db: DbSession, user: CurrentUser) -> GenerationCreateResponse:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    ensure_builtin_generation_models(db)
    try:
        generation, job = create_generation_job(db, **body.model_dump())
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
    stmt = select(GenerationJob).where(GenerationJob.workspace_id == workspace_id)
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


def _generation_model_out(model: GenerationModel) -> GenerationModelOut:
    return GenerationModelOut(
        id=model.id,
        provider=model.provider,
        kind=model.kind,
        model=model.model,
        enabled=model.enabled,
        capabilities=model.capabilities,
        adapter_available=get_provider(model.provider, model.kind) is not None,
    )


def _require_generation_session(db: DbSession, user: CurrentUser, session_id: str) -> GenerationSession:
    session = db.get(GenerationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, session.workspace_id)
    return session
