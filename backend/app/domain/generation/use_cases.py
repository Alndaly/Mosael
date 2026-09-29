"""生成的用例:会话、生成、提示词优化各自过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看会话和生成记录只要是成员(列表再按 sharing 的可见性过滤);开会话、生成、优化提示词都要 `ai` —— 都要花钱。
改、删一条会话走 sessions.writable_session(只有主人)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.unit_of_work import after_commit
from app.db.models import GenerationJob, GenerationSession, User
from app.domain import sharing
from app.domain.generation.operations import create_generation_job
from app.domain.generation.prompt_optimizer import optimize_image_prompt
from app.domain.generation.runner import start_generation_thread
from app.domain.generation.sessions import SHARE_KIND, new_session, visible_history
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm

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
    return visible_history(db, user, workspace_id, kind=kind, session_id=session_id)


# ---------------- 写 ----------------


def open_session(
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
