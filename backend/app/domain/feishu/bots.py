"""飞书机器人(`FeishuBot`)的建、改、删。一个机器人 = 一个飞书自建应用(app_id / app_secret)接进
一个工作区;它的长连接子进程由 integrations/feishu/connections 起停,状态写回这一行。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import FeishuBot


def list_bots(db: Session, workspace_id: str) -> list[FeishuBot]:
    return list(db.scalars(select(FeishuBot).where(FeishuBot.workspace_id == workspace_id).order_by(FeishuBot.created_at)))


def create_bot(db: Session, *, workspace_id: str, app_id: str, app_secret: str, **fields: Any) -> FeishuBot:
    """建一个机器人。手填(设置页)和扫码一键创建(onboarding)走的都是这一处。`fields` 是名字、能力档这类可选项。"""
    bot = FeishuBot(workspace_id=workspace_id, app_id=app_id, app_secret=app_secret, **fields)
    db.add(bot)
    db.flush()
    return bot


def update_bot(db: Session, bot: FeishuBot, changes: dict[str, Any]) -> None:
    """改名字、能力档、开关。值为 None 的项不动。"""
    for key, value in changes.items():
        if value is not None:
            setattr(bot, key, value)


def delete_bot(db: Session, bot: FeishuBot) -> None:
    db.delete(bot)


def write_status(bot_id: str, status: str, detail: str = "") -> None:
    """长连接的状态(connecting / online / offline / error)。自己开会话写:子进程、后台线程里也调它。"""
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is not None:
            bot.status = status
            bot.status_detail = detail[:400]
            db.commit()
