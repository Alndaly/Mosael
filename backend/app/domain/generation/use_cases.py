"""生成的用例:会话、生成、提示词优化各自过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看会话和生成记录只要是成员(列表再按 sharing 的可见性过滤);开会话、生成、优化提示词都要 `ai` —— 都要花钱。
改、删一条会话走 sessions.writable_session(只有主人)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.unit_of_work import after_commit
from app.db.models import GenerationJob, GenerationSession, Job, User
from app.domain import sharing
from app.domain.generation.operations import GenerationDomainError, create_generation_job
from app.domain.generation.prompt_optimizer import optimize_image_prompt
from app.domain.generation.runner import remote_poll_path, retrievable, start_generation_thread, start_retrieval_thread
from app.domain.generation.sessions import SHARE_KIND, ensure_job_writable, new_session, visible_history
from app.domain.jobs import create_job, emit_job_event
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm

#: 会话列表最多给多少条(最近用过的在前)。
SESSION_LIST_LIMIT = 50


# ---------------- 读 ----------------


def list_sessions(db: Session, user: User, workspace_id: str, kinds: list[str]) -> list[GenerationSession]:
    """这个人在这个工作区里看得见的生成会话。`kinds` 为空就是全部。"""
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(GenerationSession).where(
        GenerationSession.workspace_id == workspace_id,
        sharing.visible_filter(SHARE_KIND, user, workspace_id),
    )
    if kinds:
        stmt = stmt.where(GenerationSession.kind.in_(kinds))
    stmt = stmt.order_by(GenerationSession.updated_at.desc()).limit(SESSION_LIST_LIMIT)
    return sharing.annotate(db, SHARE_KIND, list(db.scalars(stmt)), user, workspace_id)


def history(
    db: Session, user: User, workspace_id: str, *, kind: str | None = None, session_id: str | None = None
) -> list[GenerationJob]:
    ensure_workspace_access(db, user, workspace_id)
    generations = visible_history(db, user, workspace_id, kind=kind, session_id=session_id)
    _attach_retrievable(db, generations)
    return generations


def _attach_retrievable(db: Session, generations: list[GenerationJob]) -> None:
    """失败了、但远端结果还能再取一次的那几条(见 runner.retrievable),贴到瞬态属性上 —— 界面据此在失败卡上摆「重新取回」。
    判据要看任务行和适配器,所以在这里(用例认识运行器)贴,不在 sessions 里贴(运行器经 operations 认识 sessions,反过来就是环)。"""
    job_ids = [g.job_id for g in generations if g.job_id]
    jobs = {job.id: job for job in db.scalars(select(Job).where(Job.id.in_(job_ids)))} if job_ids else {}
    for generation in generations:
        generation.retrievable = retrievable(db, generation, jobs.get(generation.job_id or ""))  # type: ignore[attr-defined]


# ---------------- 写 ----------------


def start_session(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    title: str,
    provider_profile_id: str | None,
    model: str | None,
    kind: str,
) -> GenerationSession:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    session = new_session(
        db,
        workspace_id=workspace_id,
        owner_user_id=user.id,
        title=title,
        provider_profile_id=provider_profile_id,
        model=model,
        kind=kind,
    )
    db.refresh(session)
    return sharing.annotate(db, SHARE_KIND, [session], user, workspace_id)[0]


def generate(db: Session, user: User, workspace_id: str, **request: Any) -> tuple[GenerationJob, Any]:
    """建一次生成;提交之后再派发(派发那边重开会话去读刚写的行)。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    generation, job = create_generation_job(db, created_by=user.id, workspace_id=workspace_id, **request)
    generation_id = generation.id
    after_commit(db, lambda: start_generation_thread(generation_id))
    return generation, job


def retrieve(db: Session, user: User, generation_id: str) -> tuple[GenerationJob, Job]:
    """「重新取回」:服务商那边已经做完(或者还在做)的那个远端任务,**不重新提交**,再问它要一次结果、下载、登记。

    给的是这几种失败:下载成片时断了、等远端时出了确定性的错(钥匙被换掉、六小时上限)。它们共同的地方是远端任务交出去了、
    多半扣了钱,而成片没拿到 —— 此前唯一的路是重新生成,也就是再付一次(ADR 0019 修订)。

    **建一个新任务,不复活失败的那个**:任务落了终态就是终态(任务总线的状态守卫),失败的那一次留在任务中心的历史里。
    新任务带着旧任务的载荷(远端回执、画板 / 对话的回执),生成记录改挂到新任务上;替谁干还是原来那个人 —— 远端任务
    在他的账号下,只有他的钥匙问得到。

    谁能点:和「停止」同一条(ensure_job_writable:会话主人),外加要能花钱(`ai`)。
    """
    generation = db.get(GenerationJob, generation_id)
    if generation is None:
        raise NotVisible("Not found")
    ensure_workspace_perm(db, user, generation.workspace_id, "ai")
    previous = db.get(Job, generation.job_id) if generation.job_id else None
    if previous is not None:
        ensure_job_writable(db, user, previous.id)
    if not retrievable(db, generation, previous):
        raise GenerationDomainError("genErr_notRetrievable")
    assert previous is not None  # retrievable 已经判过
    job = create_job(
        db,
        workspace_id=generation.workspace_id,
        kind="ai_generation",
        payload=dict(previous.payload or {}),
        created_by=previous.created_by,
        message="jobMsg_generationRetrieving",
    )
    generation.job_id = job.id
    #: 失败原因是上一次的:这一次还没结束,界面不该继续摆那张失败卡(见前端 turnStatus 的兜底)。
    generation.error = None
    generation.error_key = ""
    generation.error_params = {}
    emit_job_event(db, job.id, "job.retrieving", {"previous_job_id": previous.id, "poll_path": remote_poll_path(previous)})
    after_commit(db, lambda: start_retrieval_thread(generation_id))
    return generation, job


def again(db: Session, user: User, generation_id: str) -> tuple[GenerationJob, Any]:
    """「再来一次」:照这一条记着的模型和参数(提示词、反向提示词、参数、输入素材,连同第一次漏斗替他补的那几段说明)重新提交一次,
    收在同一条会话里。和点发送是同一个漏斗、同样花钱,所以和生成同一道闸(`ai`,会话得是他自己的)。

    工作台跑画布上那张图的(图不在记录里)、带驱动音频的数字人生成(授权每次都要本人勾)不行 —— 生成记录上 `repeatable` 是假,
    界面不摆这颗按钮。记着的模型现在用不了的,漏斗照常说为什么(见 generation.missing)。"""
    generation = db.get(GenerationJob, generation_id)
    if generation is None:
        raise NotVisible("Not found")
    ensure_workspace_perm(db, user, generation.workspace_id, "ai")
    request = dict(generation.request or {})
    if not generation.session_id or request.get("workbench") or request.get("digital_human_consent"):
        raise GenerationDomainError("genErr_cannotRepeat")
    created, job = create_generation_job(
        db,
        workspace_id=generation.workspace_id,
        session_id=generation.session_id,
        project_id=request.get("project_id"),
        created_by=user.id,
        provider=generation.provider,
        provider_profile_id=generation.provider_profile_id,
        model=generation.model,
        kind=generation.kind,
        prompt=str(request.get("prompt") or ""),
        negative_prompt=str(request.get("negative_prompt") or ""),
        parameters=dict(request.get("parameters") or {}),
        source_assets=[dict(one) for one in request.get("source_assets") or [] if isinstance(one, dict)],
        carried_notes=[str(one) for one in request.get("prompt_notes") or []],
    )
    created_id = created.id
    after_commit(db, lambda: start_generation_thread(created_id))
    return created, job


def optimize_prompt(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    prompt: str,
    provider: str,
    model: str,
    provider_profile_id: str | None,
    language: str,
) -> dict[str, Any]:
    """把提示词按目标图像平台的习惯优化。优化本身只读,但记了一笔用量 —— 跟着这次事务落盘。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    return optimize_image_prompt(
        db,
        user_id=user.id,
        raw_prompt=prompt,
        provider=provider,
        model=model,
        profile_id=provider_profile_id,
        ui_language=language,
    )
