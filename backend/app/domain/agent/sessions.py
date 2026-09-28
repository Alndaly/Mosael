"""对话(智能体)会话的两道闸:**看**和**写**。路由和确认卡内核都来这里问。

对话是某人的私人工作线程(见 domain/sharing.KINDS)。共享给同事是给他**看**:消息、轨迹、花费、待拍板的卡
都看得到;而在里面说话(发消息、引导 / 撤回排队的消息、停止、整理上下文、答选择卡、批确认卡)和改它
(改名、删除、收进分组、换模型 / 权限模式 / 思考档位 / 分析方式、改白名单、写计划、要求界面跳转)只有主人。
判据和生成会话一字不差,所以写在 domain/sharing(`readable` / `writable` / `ensure_writable`),这里只绑上
种类与权限档。每一条写路径被拒、读路径放行,由 tests/test_agent_session_access.py 钉着。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AgentSession, User
from app.domain import sharing

#: 共享记录里这一类叫什么(见 domain/sharing.KINDS)。
SHARE_KIND = "agent_session"


def readable_session(db: Session, user: User, session_id: str) -> AgentSession:
    """他看得见的那条对话。看不见 = 不存在(404)。"""
    return sharing.readable(db, SHARE_KIND, user, session_id)


def writable_session(db: Session, user: User, session_id: str) -> AgentSession:
    """他能写的那条对话:看得见(否则 404)+ 工作区的 `ai` 权限 + 是主人(否则 403)。"""
    return sharing.writable(db, SHARE_KIND, user, session_id, perm="ai")


def ensure_decides_for(db: Session, session_id: str | None, actor_id: str | None) -> None:
    """替一次对话拍板(批 / 拒它的确认卡)之前:这次对话有主人,就只有主人。

    不走 `writable_session`,因为确认卡还有飞书卡片回调这个入口,而飞书会话是机器人建的群聊会话 ——
    一个群一个、**没有主人**(见 integrations/feishu/service),那里的卡由群里绑定过账号的成员按工作区
    权限批(闸在 confirmations.authorize_and_*)。无主的对话不是谁的私人线程,「共享只能看」管不到它。
    没挂在任何对话上的卡(MCP 直连、工作流)同理。
    """
    if not session_id:
        return
    session = db.get(AgentSession, session_id)
    if session is None or session.owner_user_id is None:
        return
    sharing.ensure_writable(db, SHARE_KIND, session, actor_id)
