"""生成会话的两道闸:**看**和**写**。路由和生成漏斗都来这里问。

生成会话是某人的私人工作线程(见 domain/sharing.KINDS)。共享给同事是给他**看**;改名、删除、收进分组、
换模型 / 连接、在里面接着生成,只有主人。判据和对话会话一字不差,所以写在 domain/sharing
(`readable` / `writable` / `ensure_writable`),这里只绑上种类与权限档。每一条写路径被拒、读路径放行,
由 tests/test_generation_session_access.py 钉着。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import GenerationSession, User
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
