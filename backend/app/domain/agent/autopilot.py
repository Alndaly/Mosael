from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentSession, AuthSession, ToolConfirmation, User

"""自动放行:一张新开的确认卡该不该不问用户就执行。

**判定同步,执行异步。** 判定全是本地 DB 查询(会话模式、工具白名单、计数),微秒级,就地做完;
执行必须离开请求线程 —— `_execute` 是阻塞的(run_code 20s、run_http 60s),而工具体回连本 API
的客户端只等 30s,就地执行会产出「已执行但报超时」:副作用发生了,状态说没发生。

**卡的静止状态永远是 pending。** 任何一条异常路径(判定说不行、授权闸挡下、执行线程炸了、
进程崩了)都停在这里等人 —— 没有第二个"半自动"状态需要谁去回收。
"""

logger = logging.getLogger(__name__)

#: 自**上次人工决定以来**,计费卡最多连开几张。花钱这一档不能无人值守地连开,而金额上限在这里
#: 是做不了的:用量是**事后**记账(生成跑完才落账),智能体可以在任何一条账目落地之前连开二十个;
#: render 更是本地 ffmpeg,根本不产生供应商用量事件。次数是当场就能数清的那个量。
#:
#: 上限约束的是"无人值守连开",不是"一天能花多少"—— 后者需要的是账单,不是闸门。用户批一张卡,
#: 计数自然归零(他回到了现场)。
COST_AUTO_LIMIT = 5

COST_PERMISSIONS = frozenset({"ai-cost", "render-cost"})

#: 自动放行的执行线程。起名字是为了让测试能在重建 schema 前排空它 —— 不然就是那种「看机器速度
#: 和用例顺序随机红」的失败。
AUTOPILOT_THREAD_NAME = "confirmation-autopilot"


@dataclass(frozen=True)
class Decision:
    """判定结果。`mode` 会原样落进卡的留痕字段。"""

    approve: bool
    mode: str = "manual"
    detail: dict[str, Any] = field(default_factory=dict)


def wait_for_idle_autopilot(timeout: float = 5.0) -> bool:
    """等所有自动放行的执行线程跑完。给测试用 —— 生产里没人需要它。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate() if t.name == AUTOPILOT_THREAD_NAME and t.is_alive()]
        if not alive:
            return True
        alive[0].join(timeout=max(0.0, deadline - time.monotonic()))
    return not any(t.name == AUTOPILOT_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def decide(db: Session, user: User, confirmation: ToolConfirmation) -> Decision:
    """这张卡该不该自动放行。**纯读**,不改任何东西。

    顺序即优先级:没有会话 → 不是开模式的那个人 → 工具白名单 → bypass → auto 分档。
    """
    if not confirmation.session_id:
        # MCP 直连、飞书外部智能体的卡没有会话可挂模式。让它们继承任何"默认模式"就是授权范围
        # 逃逸:用户为某次对话开的口子,被一条他根本没在看的通道用掉。
        return Decision(approve=False, detail={"reason": "no-session"})
    session = db.get(AgentSession, confirmation.session_id)
    if session is None:
        return Decision(approve=False, detail={"reason": "session-gone"})
    if session.mode_set_by != user.id:
        # 飞书群聊共用一个会话(external_key 一个 chat 一个),群里任何人发消息都跑在它上面。
        # 模式是**授权动作**,只对做出授权的那个人生效。
        return Decision(approve=False, detail={"reason": "mode-set-by-someone-else"})

    permission = confirmation.permission
    if confirmation.tool in (session.auto_allow_tools or []):
        # 用户在一张读过的卡上点了「本会话始终允许」—— 逐个工具、他自己点的,与档位是两回事,
        # 所以留痕也分开记。
        return Decision(approve=True, mode="session-allow", detail={"tool": confirmation.tool})

    mode = session.permission_mode
    if mode == "bypass":
        return Decision(approve=True, mode="bypass", detail={"permission": permission})
    if mode != "auto":
        return Decision(approve=False, detail={"reason": "manual"})

    if permission == "edit":
        return Decision(approve=True, mode="auto", detail={"permission": permission})
    if permission in COST_PERMISSIONS:
        used = _billable_run_length(db, session)
        if used >= COST_AUTO_LIMIT:
            return Decision(approve=False, detail={"reason": "cost-run-limit", "used": used, "limit": COST_AUTO_LIMIT})
        return Decision(
            approve=True, mode="auto", detail={"permission": permission, "used": used, "limit": COST_AUTO_LIMIT}
        )
    # external:撤不回来的那一档。auto 不放行 —— 规则与隔离判断者是下一期的事
    # (见 docs/AGENT_PERMISSION_MODES.md §4.7)。在那之前它照常弹卡。
    return Decision(approve=False, detail={"reason": "external-needs-a-human", "permission": permission})


def _billable_run_length(db: Session, session: AgentSession) -> int:
    """自上次人工决定(或模式开启)以来,这个会话自动放行过几张计费卡。

    起点取两者中较晚的那个:用户批了一张卡就说明他回到了现场,计数该归零。
    """
    since = session.mode_set_at
    last_human = db.scalar(
        select(func.max(ToolConfirmation.resolved_at)).where(
            ToolConfirmation.session_id == session.id,
            ToolConfirmation.decision_mode == "manual",
            ToolConfirmation.resolved_at.is_not(None),
        )
    )
    if last_human is not None and (since is None or last_human > since):
        since = last_human
    stmt = select(func.count()).select_from(ToolConfirmation).where(
        ToolConfirmation.session_id == session.id,
        ToolConfirmation.decision_mode == "auto",
        ToolConfirmation.permission.in_(COST_PERMISSIONS),
    )
    if since is not None:
        stmt = stmt.where(ToolConfirmation.created_at > since)
    return int(db.scalar(stmt) or 0)


def consider(db: Session, user: User, confirmation: ToolConfirmation) -> bool:
    """判定这张新卡,决定放行就派一个线程去执行。返回是否已交给自动放行。

    留痕在**派线程之前**就落库:执行可能失败,但"这张卡是被自动放行的"这件事已经发生了,
    它不该只在执行成功时才留下记录。
    """
    decision = decide(db, user, confirmation)
    confirmation.decision_detail = decision.detail
    if not decision.approve:
        db.commit()
        return False
    confirmation.decision_mode = decision.mode
    confirmation.decided_by = user.id
    db.commit()
    threading.Thread(
        target=_execute_thread,
        args=(confirmation.id, user.id),
        daemon=True,
        name=AUTOPILOT_THREAD_NAME,
    ).start()
    return True


def _execute_thread(confirmation_id: str, user_id: str) -> None:
    """在请求线程之外批准并执行。失败一律退回 pending —— 让人来看。

    这里调的是 `authorize_and_approve`,和 HTTP 路由、飞书回调**同一个函数**:自动放行绕过的是
    「用户同意」,不是「他有没有这个权限」。三道授权闸一道不少;挡下来了就当作没有自动放行过。
    """
    from app.core.db import SessionLocal
    from app.domain.agent.confirmations import authorize_and_approve

    with SessionLocal() as db:
        confirmation = db.get(ToolConfirmation, confirmation_id)
        user = db.get(User, user_id)
        if confirmation is None or user is None:
            return
        try:
            authorize_and_approve(db, user, confirmation)
        except Exception as exc:  # noqa: BLE001 —— 含权限不足(403)、并发抢占、执行器炸了
            logger.warning("autopilot could not settle confirmation %s: %s", confirmation_id, exc)
            _fall_back_to_a_human(db, confirmation_id, str(exc))


def _fall_back_to_a_human(db: Session, confirmation_id: str, reason: str) -> None:
    """把卡放回待办。**只在它还没被认领时**动手 —— 抢占失败时它已经是别人的了。"""
    confirmation = db.get(ToolConfirmation, confirmation_id)
    if confirmation is None or confirmation.status != "pending":
        return
    confirmation.decision_mode = "manual"
    confirmation.decided_by = None
    confirmation.decision_detail = {**(confirmation.decision_detail or {}), "autopilot_failed": reason[:300]}
    db.commit()


def session_for_token(db: Session, token: str) -> str | None:
    """这份凭据属于哪次对话。归属由凭据决定,不由调用方声明(见 routes/confirmations)。"""
    auth = db.get(AuthSession, token) if token else None
    return auth.agent_session_id if auth is not None else None


__all__ = [
    "AUTOPILOT_THREAD_NAME",
    "COST_AUTO_LIMIT",
    "Decision",
    "consider",
    "decide",
    "session_for_token",
    "wait_for_idle_autopilot",
]
