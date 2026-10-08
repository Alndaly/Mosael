"""一轮结束,它留下的确认卡也结束(ADR 0007 修订 2026-10-08)。

挂在对话上的卡是那一轮**阻塞着等**的东西:sidecar 停在那次工具调用上,用户批完才把结果交给模型。一轮一结束(用户停止、卡等到点、
整轮超时、失败、甚至它照常答完了 —— 卡等到点之后模型会接着说下去),就再没有谁在等这张卡:批了照样执行,结果却送不回对话,
模型被告知的是「失败 / 没发生」。所以那一刻把它们作废,状态是 `expired`,`error` 记下由头(界面按它说人话)。
选择卡不在这里:它答了之后有兜底送回对话(questions.deliver_to_session)。

单独一个模块、只认库表:宿主(host)在一轮收尾时调它,而确认卡内核(confirmations)执行卡时要把回执接回宿主 ——
放进内核就成了 host ⇄ confirmations 的环。
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import ToolConfirmation, now

EXPIRED = "expired"
#: 卡作废的由头 —— `ToolConfirmation.error` 里记的就是这几个码(界面按码说人话,见 frontend features/agent/cardExpiry)。
EXPIRY_TURN_STOPPED = "turn_stopped"
EXPIRY_TURN_FAILED = "turn_failed"
EXPIRY_TURN_ENDED = "turn_ended"
EXPIRY_WAIT_TIMEOUT = "wait_timeout"
EXPIRY_BACKEND_RESTARTED = "backend_restarted"


def expire_session_cards(db: Session, session_id: str, reason: str) -> int:
    """这段对话还在等人的卡全部作废(一轮收尾时调;不提交,跟随调用方的事务)。返回作废了几张。

    条件更新,和认领卡(confirmations._claim)同一种写法:用户恰好在这一刻点了批准,谁先落库谁算 —— 批准赢了,这张卡就照常执行。
    """
    result = db.execute(
        update(ToolConfirmation)
        .where(ToolConfirmation.session_id == session_id, ToolConfirmation.status == "pending")
        .values(status=EXPIRED, error=reason, resolved_at=now())
        .execution_options(synchronize_session=False)
    )
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
    return confirmation


__all__ = [
    "EXPIRED",
    "EXPIRY_BACKEND_RESTARTED",
    "EXPIRY_TURN_ENDED",
    "EXPIRY_TURN_FAILED",
    "EXPIRY_TURN_STOPPED",
    "EXPIRY_WAIT_TIMEOUT",
    "expire_card",
    "expire_session_cards",
]
