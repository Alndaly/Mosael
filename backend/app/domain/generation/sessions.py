"""生成会话的两道闸:**看**和**写**。判据各只写在这里,路由和生成漏斗都来这里问。

生成会话是某人的私人工作线程(见 domain/sharing.KINDS)。主人把它共享进工作区,是给同事**看** ——
历史、产出、花费都看得到;而改名、删除、收进分组、换模型 / 连接、在里面接着生成,是**主人**的事。
此前这几件事只查了「看得见」(`sharing.may_use`),于是同事能删掉别人的会话;更隐蔽的是换模型:
会话记着的是连接,连接归个人(见 db.models.ProviderProfile),同事在别人的会话里一换模型,就把**他自己的**
连接写进了别人的会话。

「只有主人能写」和发布账号那条「借出去用、不交出去管」是同一个判据(`sharing.ensure_manageable`),
不在这里再写一遍 —— 这里只把它的拒绝翻成授权层的 403(`PermissionDenied`,见 main.py 的异常处理器),
于是路由和漏斗都不用各自 try/except。每一条写路径被拒、读路径放行,由 tests/test_generation_session_access.py 钉着。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import GenerationSession, User
from app.domain import sharing
from app.domain.permissions import NotVisible, PermissionDenied, ensure_workspace_access, ensure_workspace_perm

#: 共享记录里这一类叫什么(见 domain/sharing.KINDS)。
SHARE_KIND = "generation_session"


def readable_session(db: Session, user: User, session_id: str) -> GenerationSession:
    """他看得见的那条会话。看不见 = 不存在(404):不告诉他「这里有一条你看不到的东西」。"""
    session = db.get(GenerationSession, session_id)
    if session is None:
        raise NotVisible("Not found")
    ensure_workspace_access(db, user, session.workspace_id)
    # 看不见还不够:猜到 id 也得用不了,否则「私有」只是列表上的一层遮挡。
    if not sharing.may_use(db, SHARE_KIND, session, user.id):
        raise NotVisible("Not found")
    return session


def writable_session(db: Session, user: User, session_id: str) -> GenerationSession:
    """他能改的那条会话:先得看得见(否则 404),再得有工作区的 `ai` 权限,再得是主人(否则 403)。"""
    session = readable_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    ensure_writable(db, session, user.id)
    return session


def ensure_writable(db: Session, session: GenerationSession, actor_id: str | None) -> None:
    """写之前的最后一道:只有主人。生成漏斗往一条点了名的会话里放生成之前也过这里。"""
    try:
        sharing.ensure_manageable(db, SHARE_KIND, session, actor=actor_id)
    except sharing.NotManageableError as exc:
        raise PermissionDenied.relay(exc) from exc
