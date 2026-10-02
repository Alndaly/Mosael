"""后台任务干完之后,把回执送回发起它的那次对话。

智能体提交一次生成之后就断了线索:它只知道「提交成功」,不知道跑完没有。表现是两种,
哪一种都不好 —— 要么反复 get_job 轮询(用户看着它一遍遍查同一件事),要么干脆当作没这回事,
让用户自己回来问「好了吗」。而任务这一层本来就知道自己什么时候结束。

**方向是反的:任务不认识智能体,是这里认识任务。** 登记在装配层(app/main.py),和
tts_runtime_config 那条同一个做法 —— 发布、导出、转写都建任务,它们没有一个该因为
「智能体也许想知道」而依赖智能体域。

**回执不是用户消息。** 此前它借用户的名义进会话(post_user_message + from_job),会话正忙就进了排队:
输入框上方排出七八条「已完成」,带着 Steer 和删除,这一轮之后又每条各跑一轮。现在它落成自己的角色
(host.JOB_RECEIPT_ROLE),怎么交给智能体见 host.post_job_receipt。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentMessage, AgentSession, Job, User
from app.domain.agent import host
from app.domain.jobs import TERMINAL_STATUSES, register_receipt_deliverer

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
        # 这句摘要要覆盖**所有**任务种类,而它们的产出形状本来就不同:渲染、配音一次出一份
        # (asset_id),生成可能出多份(asset_ids —— 图像接口的 n)。两个都读,不是兼容旧字段,
        # 是这两种形状同时真实存在。
        ids = [str(one) for one in (result.get("asset_ids") or []) if one]
        if not ids and result.get("asset_id"):
            ids = [str(result["asset_id"])]
        # 素材 id 是模型下一步真正要用的东西(插进时间线、当下一次生成的首帧)。
        # 只说「完成了」的话,它还得再查一次任务才拿得到。
        tail = f",素材 id:{'、'.join(ids)}" if ids else ""
        return f"{what}已完成{tail}。"
    reason = str(job.error or job.message or "").strip()
    return f"{what}失败了{f':{reason}' if reason else ''}。"


def deliver(db: Session, job: Job, receipt: dict[str, Any]) -> None:
    # 智能体自己已经盯着它跑完了(见 acknowledge_seen):再送一句只会让它多跑一轮去说「收到」。
    if receipt.get("seen"):
        return
    session = db.get(AgentSession, str(receipt.get("session_id") or ""))
    if session is None:
        return
    # 回执交给智能体之后,那一轮以谁的身份跑:建这个任务的那个人。会话是私人的,而起一轮要一个主体来
    # 铸服务令牌 —— 拿不到人就不送,而不是找一个凑数的。
    owner = db.get(User, str(job.created_by or "")) if job.created_by else None
    if owner is None:
        logger.warning("job %s 的回执没送:任务没有归属人", job.id)
        return
    host.post_job_receipt(db, session, _summarize(job), owner, job_id=job.id)


def acknowledge_seen(db: Session, _user: User, job_id: str, session_id: str) -> None:
    """智能体在这次对话里**亲眼看到**这个任务到了终态(get_job 查到的):它的回执就不必再送了。

    回执是给「提交之后就断了线索」的那种情况的。智能体一直在轮询、已经拿到结果接着做完了的话,那句回执
    还是会来 —— 它在这一轮跑着的时候到,等这一轮结束又交给智能体跑一轮,智能体回一句
    「收到,这正是刚才那次解析的回执,不需要再做别的处理」(用户截图:「这种回执本身智能体调用 job 获取结果中
    就有了的吧,为何还会独立显示」)。

    两个先后都要管:回执已经落库、还没交给智能体 —— 拿掉它;还没送 —— 在任务上记一笔,送的时候跳过。
    只认发给**这次对话**的回执:别的会话起的任务,这里看一眼不代表那边知道了。
    """
    job = db.get(Job, job_id)
    if job is None or job.status not in TERMINAL_STATUSES:
        return
    receipt = (job.payload or {}).get("receipt")
    if not isinstance(receipt, dict) or receipt.get("kind") != RECEIPT_KIND or receipt.get("session_id") != session_id:
        return
    if not receipt.get("seen"):
        job.payload = {**(job.payload or {}), "receipt": {**receipt, "seen": True}}
    waiting = db.scalars(
        select(AgentMessage).where(AgentMessage.session_id == session_id, AgentMessage.role == host.JOB_RECEIPT_ROLE)
    )
    for message in waiting:
        payload = message.payload or {}
        if payload.get("undelivered") and payload.get("job_id") == job.id:
            db.delete(message)


def install() -> None:
    register_receipt_deliverer(RECEIPT_KIND, deliver)
