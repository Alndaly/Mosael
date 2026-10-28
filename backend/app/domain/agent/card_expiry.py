"""一轮结束,它留下的确认卡也结束(ADR 0007 修订 2026-10-08);后端重启,上一进程认领了却没落结果的卡记「未知」。

挂在对话上的卡是那一轮**阻塞着等**的东西:sidecar 停在那次工具调用上,用户批完才把结果交给模型。一轮一结束(用户停止、卡等到点、
整轮超时、失败、甚至它照常答完了 —— 卡等到点之后模型会接着说下去),就再没有谁在等这张卡:批了照样执行,结果却送不回对话,
模型被告知的是「失败 / 没发生」。所以那一刻把它们作废,状态是 `expired`,`error` 记下由头(界面按它说人话)。
选择卡不在这里:它答了之后有兜底送回对话(questions.deliver_to_session)。

第二种情况是**已经批准**的卡:认领(`confirmations._claim`)先提交 `approved` 再执行,进程死在中间时
卡永远停在那一态 —— 批过的动作到底做没做,没人知道。这种卡**不作废、也不算失败**:重启收尾把
它记成 `unknown`(`resolve_interrupted_executions`),说清「结果未知」,并且绝不自动重跑。

单独一个模块、只认库表:宿主(host)在一轮收尾时调它,而确认卡内核(confirmations)执行卡时要把回执接回宿主 ——
放进内核就成了 host ⇄ confirmations 的环。
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.unit_of_work import after_commit
from app.db.models import ToolConfirmation, now
from app.domain.agent import origins

EXPIRED = "expired"
#: 卡作废的由头 —— `ToolConfirmation.error` 里记的就是这几个码(界面按码说人话,见 frontend features/agent/cardExpiry)。
EXPIRY_TURN_STOPPED = "turn_stopped"
EXPIRY_TURN_FAILED = "turn_failed"
EXPIRY_TURN_ENDED = "turn_ended"
EXPIRY_WAIT_TIMEOUT = "wait_timeout"
EXPIRY_BACKEND_RESTARTED = "backend_restarted"

#: **执行结果未知**:卡已经被认领(`approved`,见 confirmations._claim),进程在落结果之前没了。
#: 这不是「没做」也不是「失败」—— 动作可能已经生效一半,也可能一步都没走。所以它自成一态:
#: 批准接口一律回 409(不能再来一次),界面如实说「不知道」,而**绝不自动重跑**。
UNKNOWN = "unknown"
EXECUTION_UNKNOWN = "execution_unknown"


def _notify_settled(db: Session, confirmation_id: str) -> None:

    after_commit(db, lambda one=confirmation_id: origins.confirmation_settled_by_id_after_commit(one))


def resolve_interrupted_executions(db: Session) -> int:
    """**只在重启收尾里调**:上一个进程认领了、却没落结果的卡,记成 `unknown`。返回收了几张。

    认领那一步(`confirmations._claim`)是**先提交 approved、再执行**:执行器可能很慢、可能付费,
    进程恰好死在这中间时,卡就永远停在 approved —— 界面上写着「正在执行」转个不停,而审批接口
    回 409,没人能把它结掉。批过的动作到底做没做,库里的答案只能是「不知道」。

    不区分 session_id:认领是**本进程**做的,不管这张卡挂在哪条对话上(外部智能体开的卡也一样),
    重启之后本进程里没有在执行的卡 —— 此刻的 approved 一定是上一个进程留下的。

    不自动重跑:这正是这张卡要挡住的事。重跑是用户的决定,而他要先看得见「不知道」。
    """
    ids = list(db.scalars(select(ToolConfirmation.id).where(ToolConfirmation.status == "approved")))
    if not ids:
        return 0
    result = db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.id.in_(ids), ToolConfirmation.status == "approved")
        .values(status=UNKNOWN, error=EXECUTION_UNKNOWN, resolved_at=now())
        .execution_options(synchronize_session=False)
    )
    for confirmation_id in ids:
        _notify_settled(db, confirmation_id)
    return int(result.rowcount or 0)


def expire_session_cards(db: Session, session_id: str, reason: str) -> int:
    """这段对话还在等人的卡全部作废(一轮收尾时调;不提交,跟随调用方的事务)。返回作废了几张。

    条件更新,和认领卡(confirmations._claim)同一种写法:用户恰好在这一刻点了批准,谁先落库谁算 —— 批准赢了,这张卡就照常执行。
    """
    ids = list(
        db.scalars(
            select(ToolConfirmation.id).where(
                ToolConfirmation.session_id == session_id, ToolConfirmation.status == "pending"
            )
        )
    )
    result = db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.session_id == session_id, ToolConfirmation.status == "pending")
        .values(status=EXPIRED, error=reason, resolved_at=now())
        .execution_options(synchronize_session=False)
    )
    for confirmation_id in ids:
        _notify_settled(db, confirmation_id)
    return int(result.rowcount or 0)


def expire_card(db: Session, confirmation: ToolConfirmation, reason: str) -> ToolConfirmation:
    """作废这一张(sidecar 等到点了:模型将被告知「没做」,这张卡就不能再被批)。已经有结论的原样返回。不提交。"""
    db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.id == confirmation.id, ToolConfirmation.status == "pending")
        .values(status=EXPIRED, error=reason, resolved_at=now())
        .execution_options(synchronize_session=False)
    )
    db.flush()
    db.refresh(confirmation)
    if confirmation.status == EXPIRED:
        _notify_settled(db, confirmation.id)
    return confirmation


__all__ = [
    "EXECUTION_UNKNOWN",
    "EXPIRED",
    "EXPIRY_BACKEND_RESTARTED",
    "EXPIRY_TURN_ENDED",
    "EXPIRY_TURN_FAILED",
    "EXPIRY_TURN_STOPPED",
    "EXPIRY_WAIT_TIMEOUT",
    "UNKNOWN",
    "expire_card",
    "expire_session_cards",
    "resolve_interrupted_executions",
]
