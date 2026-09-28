"""生成会话的两道闸:**看**和**写**。路由和生成漏斗都来这里问。

生成会话是某人的私人工作线程(见 domain/sharing.KINDS)。共享给同事是给他**看**;改名、删除、收进分组、
换模型 / 连接、在里面接着生成,只有主人。判据和对话会话一字不差,所以写在 domain/sharing
(`readable` / `writable` / `ensure_writable`),这里只绑上种类与权限档。每一条写路径被拒、读路径放行,
由 tests/test_generation_session_access.py 钉着。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationJob, GenerationSession, User
from app.domain import sharing

#: 共享记录里这一类叫什么(见 domain/sharing.KINDS)。
SHARE_KIND = "generation_session"


def readable_session(db: Session, user: User, session_id: str) -> GenerationSession:
    """他看得见的那条会话。看不见 = 不存在(404)。"""
    return sharing.readable(db, SHARE_KIND, user, session_id)


def writable_session(db: Session, user: User, session_id: str) -> GenerationSession:
    """他能改的那条会话:看得见(否则 404)+ 工作区的 `ai` 权限 + 是主人(否则 403)。"""
    return sharing.writable(db, SHARE_KIND, user, session_id, perm="ai")


def ensure_writable(db: Session, session: GenerationSession, actor_id: str | None) -> None:
    """写之前的最后一道:只有主人。生成漏斗往一条点了名的会话里放生成之前也过这里。"""
    sharing.ensure_writable(db, SHARE_KIND, session, actor_id)


# ---------- 任务总线上的生成 ----------
#
# 每次生成在任务总线(`jobs` 表)上也有一行,任务中心、生成页的进度都从那里读 —— 而那一行的 payload 里就是提示词
# 和整份请求。所以总线上的这一行跟着它那条生成所在的会话走:看不见那条会话,就看不见这个任务(否则「私有」
# 只挡住了会话列表,内容还在任务中心里);取消它是在那条会话里写,只有主人。不挂在生成记录上的任务(导出、转写、
# 工作流……)是工作区的,不受这里管。


def jobs_filter(job_id_column: Any, user: User, workspace_id: str) -> Any:
    """`jobs` 表上他看得见的那些(SQL 条件)。`job_id_column` 是任务 id 那一列。"""
    visible_sessions = select(GenerationSession.id).where(sharing.visible_filter(SHARE_KIND, user, workspace_id))
    hidden = select(GenerationJob.job_id).where(
        GenerationJob.job_id.is_not(None),
        GenerationJob.session_id.is_not(None),
        GenerationJob.session_id.not_in(visible_sessions),
    )
    return job_id_column.not_in(hidden)


def ensure_job_readable(db: Session, user: User, job_id: str) -> None:
    """按 id 看一个任务之前。它是某条会话里的生成时,得看得见那条会话(否则 404)。"""
    _session_of_job(db, user, job_id)


def ensure_job_writable(db: Session, user: User, job_id: str) -> None:
    """取消一个任务之前。它是某条会话里的生成时,得看得见(否则 404)且是会话主人(否则 403)。"""
    session = _session_of_job(db, user, job_id)
    if session is not None:
        ensure_writable(db, session, user.id)


def _session_of_job(db: Session, user: User, job_id: str) -> GenerationSession | None:
    session_id = db.scalar(select(GenerationJob.session_id).where(GenerationJob.job_id == job_id))
    return readable_session(db, user, session_id) if session_id else None
