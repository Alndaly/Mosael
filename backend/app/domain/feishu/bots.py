"""飞书机器人(`FeishuBot`)的建、改、删。一个机器人 = 一个飞书自建应用(app_id / app_secret)接进
一个工作区;它的长连接子进程由 integrations/feishu/connections 起停,状态写回这一行。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.unit_of_work import unit_of_work
from app.db.models import FeishuBinding, FeishuBot
from app.domain.feishu import bindings


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
    """删机器人:它名下的绑定**一起走** —— `feishu_bindings.bot_id` 上的外键是 `ON DELETE CASCADE`
    (见 db/model_slices/feishu.FeishuBinding),`db.delete` 之后数据库自己把它们删掉。

    不标 stale、不留行:`(bot, open_id) -> user` 这条绑定随机器人一起没有意义 —— open_id 按飞书应用
    隔离,那台应用没了之后它眼里的那串 id 不再有任何应用解释得了,留着就是一行**谁都匹配不上**的死行。

    **「谁曾绑过」走审计表,不走这张活跃表**(见 `bindings.record_removed` / ADR 0070 §9):
    删之前把它名下**每一条**绑定各记一条历史 —— 否则级联删完就"查无此事"了。记的是历史事件,
    不是把行标成已删:绑定表里照旧一条不留(已删的状态写回去,换来的正是这套刚删掉的东西)。
    """
    for binding in db.scalars(
        select(FeishuBinding).where(
            FeishuBinding.workspace_id == bot.workspace_id, FeishuBinding.bot_id == bot.id
        )
    ):
        bindings.record_removed(
            db,
            workspace_id=bot.workspace_id,
            bot_id=bot.id,
            open_id=binding.open_id,
            user_id=binding.user_id,
            app_id=bot.app_id,
            bot_name=bot.name,
            whole_bot=True,
        )
    db.delete(bot)


def write_status(bot_id: str, status: str, detail: str = "") -> None:
    """长连接的状态(connecting / online / offline / error)。自己开会话写:子进程、后台线程里也调它。"""
    with unit_of_work() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is not None:
            bot.status = status
            bot.status_detail = detail[:400]
