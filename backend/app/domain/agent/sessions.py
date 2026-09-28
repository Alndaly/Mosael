"""对话(智能体)会话的两道闸:**看**和**写**。路由和确认卡内核都来这里问。

对话是某人的私人工作线程(见 domain/sharing.KINDS)。共享给同事是给他**看**:消息、轨迹、花费、待拍板的卡
都看得到;而在里面说话(发消息、引导 / 撤回排队的消息、停止、整理上下文、答选择卡、批确认卡)和改它
(改名、删除、收进分组、换模型 / 权限模式 / 思考档位 / 分析方式、改白名单、写计划、要求界面跳转)只有主人。
判据和生成会话一字不差,所以写在 domain/sharing(`readable` / `writable` / `ensure_writable`),这里只绑上
种类与权限档。每一条写路径被拒、读路径放行,由 tests/test_agent_session_access.py 钉着。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentSession, User
from app.domain import sharing
from app.domain.permissions import NotVisible

#: 共享记录里这一类叫什么(见 domain/sharing.KINDS)。
SHARE_KIND = "agent_session"


def readable_session(db: Session, user: User, session_id: str) -> AgentSession:
    """他看得见的那条对话。看不见 = 不存在(404)。"""
    return sharing.readable(db, SHARE_KIND, user, session_id)


def writable_session(db: Session, user: User, session_id: str) -> AgentSession:
    """他能写的那条对话:看得见(否则 404)+ 工作区的 `ai` 权限 + 是主人(否则 403)。"""
    return sharing.writable(db, SHARE_KIND, user, session_id, perm="ai")


# ---------- 挂在对话上的东西:确认卡 ----------
#
# 一张确认卡跟着发起它的那次对话走。对话有主人,卡就是主人私人线程里的东西:看得见那次对话的人(主人,或主人
# 共享进了工作区)才看得见卡,只有主人能替它拍板。没挂在对话上的(MCP 直连、工作流)和挂在**无主**对话上的
# (飞书群聊会话:一个群一个、机器人建的,见 integrations/feishu/service)是**工作区的**卡 —— 全局确认中心
# 靠它们兜底,工作区的人都看得见,按工作区权限批。工作区成员关系由调用方先查。
#
# 挂着的那次对话已经删掉的卡(卡上的会话 id 不设外键,见 db.models.ToolConfirmation),看不见也批不了:删掉的是
# 某人的私人线程,留下的卡(工具名、参数)不该因此变成全工作区可读。


def ensure_reads_for(db: Session, session_id: str | None, actor_id: str | None) -> None:
    """看一张挂在对话上的卡之前。看不见 = 不存在(`NotVisible`,api 回 404)。"""
    _owned_session_seen_by(db, session_id, actor_id)


def ensure_decides_for(db: Session, session_id: str | None, actor_id: str | None) -> None:
    """替一次对话拍板(批 / 拒它的确认卡)之前:先得看得见(否则 404),对话有主人就只有主人(否则 403)。

    不走 `writable_session`:飞书卡片回调也来这里,而飞书群聊会话没有主人,那里的卡由群里绑定过账号的成员
    按工作区权限批(闸在 confirmations.authorize_and_*)。「共享只能看」管不到无主的对话。
    """
    session = _owned_session_seen_by(db, session_id, actor_id)
    if session is not None:
        sharing.ensure_writable(db, SHARE_KIND, session, actor_id)


def reads_for_filter(session_id_column: Any, actor_id: str | None, workspace_id: str) -> Any:
    """`ensure_reads_for` 的 SQL 版:`session_id_column` 是卡上挂靠会话的那一列。一次查询筛完整张列表。"""
    seen = select(AgentSession.id).where(
        AgentSession.owner_user_id.is_(None) | sharing.usable_filter(SHARE_KIND, actor_id, workspace_id)
    )
    return session_id_column.is_(None) | session_id_column.in_(seen)


def _owned_session_seen_by(db: Session, session_id: str | None, actor_id: str | None) -> AgentSession | None:
    """卡挂着的那次对话 —— 有主人时返回它(调用方据此再问写),没挂 / 无主时 None;看不见就抛 `NotVisible`。"""
    if not session_id:
        return None
    session = db.get(AgentSession, session_id)
    if session is None:
        raise NotVisible("Not found")
    if session.owner_user_id is None:
        return None
    if not sharing.may_use(db, SHARE_KIND, session, actor_id):
        raise NotVisible("Not found")
    return session
