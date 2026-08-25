"""后台任务干完之后,把回执送回发起它的那次对话。

智能体提交一次生成之后就断了线索:它只知道「提交成功」,不知道跑完没有。表现是两种,
哪一种都不好 —— 要么反复 get_job 轮询(用户看着它一遍遍查同一件事),要么干脆当作没这回事,
让用户自己回来问「好了吗」。而任务这一层本来就知道自己什么时候结束。

**方向是反的:任务不认识智能体,是这里认识任务。** 登记在装配层(app/main.py),和
tts_runtime_config 那条同一个做法 —— 发布、导出、转写都建任务,它们没有一个该因为
「智能体也许想知道」而依赖智能体域。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AgentSession, Job, User
from app.domain.agent import host
from app.domain.jobs import register_receipt_deliverer

logger = logging.getLogger(__name__)

RECEIPT_KIND = "agent_session"


def receipt_to_session(session_id: str) -> dict[str, Any]:
    """建任务时写进 payload 的那一小块。"""
    return {"kind": RECEIPT_KIND, "session_id": session_id}


def _summarize(job: Job) -> str:
    """回执的正文 —— 用户在对话里看到的也是这一句,所以它要像人话。"""
    subject = str((job.payload or {}).get("subject") or "").strip()
    what = f"「{subject}」" if subject else "刚才那个任务"
    if job.status == "succeeded":
        result = job.result or {}
        asset_id = str(result.get("asset_id") or "")
        # 素材 id 是模型下一步真正要用的东西(插进时间线、当下一次生成的首帧)。
        # 只说「完成了」的话,它还得再查一次任务才拿得到。
        tail = f",素材 id:{asset_id}" if asset_id else ""
        return f"{what}已完成{tail}。"
    reason = str(job.error or job.message or "").strip()
    return f"{what}失败了{f':{reason}' if reason else ''}。"


def deliver(db: Session, job: Job, receipt: dict[str, Any]) -> None:
    session = db.get(AgentSession, str(receipt.get("session_id") or ""))
    if session is None:
        return
    # 回执替谁说话:建这个任务的那个人。会话是私人的,而 post_user_message 要一个主体来
    # 铸服务令牌 —— 拿不到人就不送,而不是找一个凑数的。
    owner = db.get(User, str(job.created_by or "")) if job.created_by else None
    if owner is None:
        logger.warning("job %s 的回执没送:任务没有归属人", job.id)
        return
    host.post_user_message(db, session, _summarize(job), owner, origin_job_id=job.id)


def install() -> None:
    register_receipt_deliverer(RECEIPT_KIND, deliver)
