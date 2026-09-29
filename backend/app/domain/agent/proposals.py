"""开一张确认卡的**完整**流程,所有入口共用:过闸 → 建卡 → 判自动放行 → 推到它该出现的地方。

此前这四步写在 `POST /api/confirmations` 这条路由里,智能体的工具经 HTTP 回连来借用它。工具改成直接调领域
之后,四步必须在领域里:否则直接开的卡会少掉其中某一步 —— 最容易漏的是最后那一步(推到飞书),因为它此前
被特意放在路由层以避开 confirmations ⇄ feishu 的循环依赖。现在推送经 `origins.confirmation_opened` 交给
登记过的渠道,领域不认识飞书。

单独一个模块:它同时要 confirmations 和 autopilot,而 autopilot 回头会用 confirmations —— 放进任何一方都成环。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ToolConfirmation, User
from app.domain.agent import autopilot, origins
from app.domain.agent.confirmations import request_confirmation
from app.domain.permissions import ensure_workspace_perm


def propose(
    db: Session,
    user: User,
    *,
    workspace_id: str,
    tool: str,
    payload: dict[str, Any],
    requested_by: str = "",
    session_id: str | None = None,
) -> ToolConfirmation:
    """开一张卡。`session_id` 是这次调用**凭据**所属的对话(由入口从令牌取出),不是调用方自己声明的 ——
    声明的话就能把自己的动作挂进别人的对话(三档权限模式下,那等于挂进别人开的自动放行)。

    开卡要 edit 权限:卡批了就会改东西,不能让只读的人借一张卡去改。
    """
    ensure_workspace_perm(db, user, workspace_id, "edit")
    confirmation = request_confirmation(
        db,
        workspace_id=workspace_id,
        tool=tool,
        payload=payload,
        actor_id=user.id,
        requested_by=requested_by,
        session_id=session_id,
    )
    # 该不该不问就执行。判定就地做完(全是本地查询),执行交给后台线程 —— 放行了就不必再问用户,
    # 飞书那边也不用推一张没人需要点的卡。
    if autopilot.consider(db, user, confirmation):
        return confirmation
    origins.confirmation_opened(db, confirmation)
    return confirmation
