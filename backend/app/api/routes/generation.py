from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    CapabilityProfileSchemaOut,
    GenerationCreate,
    GenerationCreateResponse,
    GenerationJobOut,
    GenerationOptionOut,
    GenerationSessionCreate,
    GenerationUnavailableOut,
    GenerationSessionOut,
    GenerationSessionUpdate,
    PromptOptimizeRequest,
    PromptOptimizeResponse,
)
from app.domain.permissions import require_own_profile
from app.db.models import GenerationJob, GenerationSession
from app.domain import session_groups, sharing
from app.domain.generation import generation_options
from app.domain.generation import use_cases as generation
from app.domain.generation.operations import GenerationDomainError
from app.domain.generation.custom_profiles import capability_ref_choices
from app.domain.generation.prompt_optimizer import PromptOptimizeError
from app.domain.generation.sessions import SHARE_KIND, delete_session, writable_session

router = APIRouter(tags=["generation"])


@router.post("/generation/sessions", response_model=GenerationSessionOut)
def create_generation_session(
    body: GenerationSessionCreate, db: Tx, user: CurrentUser
) -> GenerationSession:
    fields = body.model_dump()
    return generation.start_session(db, user, fields.pop("workspace_id"), **fields)


@router.get("/generation/sessions", response_model=list[GenerationSessionOut])
def list_generation_sessions(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: list[str] = Query(default_factory=list),
) -> list[GenerationSession]:
    """这个人在这个工作区里看得见的生成会话。`kind` 可以给几个:AI 工作台「生成」页要图像和视频,
    「音频」页要音频 —— 在这里筛而不是在界面上筛,因为列表有条数上限,界面筛的话一页的会话能把
    另一页的挤出去。"""
    return generation.list_sessions(db, user, workspace_id, kind)


@router.patch("/generation/sessions/{session_id}", response_model=GenerationSessionOut)
def update_generation_session(
    session_id: str, body: GenerationSessionUpdate, db: DbSession, user: CurrentUser
) -> GenerationSession:
    session = writable_session(db, user, session_id)
    fields = body.model_fields_set
    # 只改了分组就不算活动(见 session_groups.restore_updated_at)。
    organising_only = fields <= {"group_id"} and body.group_id is not None
    kept_updated_at = session.updated_at
    if "title" in fields and body.title is not None:
        session.title = body.title
    if "group_id" in fields:
        session_groups.move_into(db, session, body.group_id or "", kind="generation")
    if "provider_profile_id" in fields:
        session.provider_profile_id = body.provider_profile_id
    if "model" in fields:
        session.model = body.model
    if "kind" in fields and body.kind is not None:
        session.kind = body.kind
    db.commit()
    if organising_only:
        session_groups.restore_updated_at(db, session, kept_updated_at)
        db.commit()
    db.refresh(session)
    return sharing.annotate(db, SHARE_KIND, [session], user, session.workspace_id)[0]


@router.delete("/generation/sessions/{session_id}", status_code=204)
def delete_generation_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    delete_session(db, writable_session(db, user, session_id))
    db.commit()
    return Response(status_code=204)


@router.get("/generation/options", response_model=list[GenerationOptionOut])
def list_generation_options(db: DbSession, user: CurrentUser, kind: str = "image") -> list[GenerationOptionOut]:
    """能用来生成的 (连接 × 模型)。设置页里加了什么,这里就有什么 —— 同一个来源。"""
    return [GenerationOptionOut(**option) for option in generation_options(db, kind, user_id=user.id)]


@router.get("/generation/unavailable", response_model=list[GenerationUnavailableOut])
def list_unavailable_models(db: DbSession, user: CurrentUser) -> list[GenerationUnavailableOut]:
    """插件连接上「认得、现在用不了」的模型和为什么:选着它们的格子、会话据此说清楚该去哪(ADR 0045 §7)。"""
    from app.domain.generation.resolution import unavailable_models

    return [GenerationUnavailableOut(**one) for one in unavailable_models(db, user_id=user.id)]


@router.get("/generation/capability-profile-schema", response_model=CapabilityProfileSchemaOut)
def get_capability_profile_schema(kind: str = "image") -> CapabilityProfileSchemaOut:
    """参数组可视表单的结构描述 —— 34 个字段的键/形状/分组,和这个 kind 的参数与素材角色。

    前端的语义表单由它驱动:加一个字段只改后端 custom_profiles 一处,表单自动长出
    对应的控件。键名与分组的翻译在前端(messages.ts),后端不出文案。
    """
    from app.domain.generation.custom_profiles import profile_form_schema

    from app.domain.generation.catalog import GENERATION_KINDS

    if kind not in GENERATION_KINDS:
        raise HTTPException(status_code=422, detail=tr("routeErr_badGenerationKind"))
    return CapabilityProfileSchemaOut(**profile_form_schema(kind))


@router.get("/generation/capability-refs")
def list_capability_refs(
    db: DbSession, user: CurrentUser, kind: str = "image", profile_id: str | None = None
) -> dict[str, list[Any]]:
    """设置页里「这一行的生成参数按什么来」能选什么。

    两组,对应那一列的两种写法:

      `models`   目录认得的 (provider, model) —— 「它和 X 一样」。**首选** ,因为它是指针:
                 以后我们把 X 的描述符改宽了,指着它的行跟着变。
      `profiles` 能力档案本身 —— 目录里没有对应模型时(某个中转独有的组合)才用得上。

    两边都带上 `parameter_keys`,好让用户在选之前就看得见"选它会得到哪几项",而不是选完
    回去翻界面。
    """
    profile = require_own_profile(db, user, profile_id) if profile_id else None
    return capability_ref_choices(db, kind, profile)


@router.post("/generation/optimize-prompt", response_model=PromptOptimizeResponse)
def optimize_prompt(body: PromptOptimizeRequest, db: Tx, user: CurrentUser) -> PromptOptimizeResponse:
    """把提示词按目标图像平台(provider/model)的习惯优化。前端「优化」按钮与智能助手技能共用。"""
    fields = body.model_dump()
    try:
        result = generation.optimize_prompt(db, user, fields.pop("workspace_id"), **fields)
    except PromptOptimizeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PromptOptimizeResponse(**result)


@router.post("/generation/jobs", response_model=GenerationCreateResponse)
def create_generation(body: GenerationCreate, db: Tx, user: CurrentUser) -> GenerationCreateResponse:
    fields = body.model_dump()
    try:
        created, job = generation.generate(db, user, fields.pop("workspace_id"), **fields)
    except GenerationDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GenerationCreateResponse(
        generation=GenerationJobOut.model_validate(created),
        job=job,
    )


@router.post("/generation/jobs/{generation_id}/retrieve", response_model=GenerationCreateResponse)
def retrieve_generation(generation_id: str, db: Tx, user: CurrentUser) -> GenerationCreateResponse:
    """重新取回:服务商那边已经做完的那一次,不重新提交、不再付钱,再问它要一次结果。只对 `retrievable` 的记录有效,
    别的一律 409。谁能点和「停止」同一条(会话主人)。"""
    try:
        record, job = generation.retrieve(db, user, generation_id)
    except GenerationDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GenerationCreateResponse(generation=GenerationJobOut.model_validate(record), job=job)


@router.get("/generation/jobs", response_model=list[GenerationJobOut])
def list_generation_jobs(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str | None = None,
    session_id: str | None = None,
) -> list[GenerationJob]:
    return generation.history(db, user, workspace_id, kind=kind, session_id=session_id)
