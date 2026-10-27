"""开一张确认卡的**完整**流程,所有入口共用:过闸 → 建卡 → 判自动放行 → 推到它该出现的地方。

此前这四步写在 `POST /api/confirmations` 这条路由里,智能体的工具经 HTTP 回连来借用它。工具改成直接调领域
之后,四步必须在领域里:否则直接开的卡会少掉其中某一步 —— 最容易漏的是最后那一步(推到飞书),因为它此前
被特意放在路由层以避开 confirmations ⇄ feishu 的循环依赖。现在推送经 `origins.confirmation_opened` 交给
登记过的渠道,领域不认识飞书。

单独一个模块:它同时要 confirmations 和 autopilot,而 autopilot 回头会用 confirmations —— 放进任何一方都成环。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.unit_of_work import after_commit
from app.db.models import ToolConfirmation, User
from app.domain.agent import autopilot, origins
from app.domain.agent.confirmations import _prepare_confirmation
from app.domain.permissions import ensure_workspace_perm


def _for_tool_call(db: Session, session_id: str | None, tool_call_id: str | None) -> ToolConfirmation | None:
    """同一对话里这次工具调用已经开过的卡。没有完整身份的外部调用不参与去重。"""
    if not session_id or not tool_call_id:
        return None
    return db.scalar(
        select(ToolConfirmation).where(
            ToolConfirmation.session_id == session_id,
            ToolConfirmation.tool_call_id == tool_call_id,
        )
    )


def propose(
    db: Session,
    user: User,
    *,
    workspace_id: str,
    tool: str,
    payload: dict[str, Any],
    requested_by: str = "",
    session_id: str | None = None,
    tool_call_id: str | None = None,
) -> ToolConfirmation:
    """开一张卡。`session_id` 是这次调用**凭据**所属的对话(由入口从令牌取出),不是调用方自己声明的 ——
    声明的话就能把自己的动作挂进别人的对话(三档权限模式下,那等于挂进别人开的自动放行)。

    `tool_call_id` 反过来**可以**由调用方报:它只决定卡在对话里摆在哪一步(见 ToolConfirmation.tool_call_id)。

    开卡要 edit 权限:卡批了就会改东西,不能让只读的人借一张卡去改。
    """
    ensure_workspace_perm(db, user, workspace_id, "edit")
    existing = _for_tool_call(db, session_id, tool_call_id)
    if existing is not None:
        return existing
    # validate 可能经独立连接写入(例如工作台连接),所以先在 SAVEPOINT 外完成;
    # 只有真正 insert 进保存点,唯一键冲突时回滚这一点,调用方其余事务不受影响。
    confirmation = _prepare_confirmation(
        db, workspace_id=workspace_id, tool=tool, payload=payload, actor_id=user.id,
        requested_by=requested_by, session_id=session_id, tool_call_id=tool_call_id,
    )
    try:
        with db.begin_nested():
            db.add(confirmation)
            db.flush()
            db.refresh(confirmation)
    except IntegrityError:
        existing = _for_tool_call(db, session_id, tool_call_id)
        if existing is not None:
            return existing
        raise
    # 该不该不问就执行。判定就地做完(全是本地查询),执行交给后台线程 —— 放行了就不必再问用户,
    # 飞书那边也不用推一张没人需要点的卡。
    if autopilot.consider(db, user, confirmation):
        return confirmation
    # 卡片必须等这次事务提交后再发:飞书那边点得快,回调会在行还不可见时到达;请求失败回滚时,
    # 提前发出的卡也会变成一张永远点不动的死卡。推送本身是集成层的事,这里只登记提交后钩子。
    after_commit(db, lambda: origins.confirmation_opened_after_commit(confirmation))
    return confirmation
