"""飞书机器人的用例:按机器人所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看机器人和绑定不点名权限;建、改、删、生成绑定码点名 edit;解除别人的绑定是成员管理,点名 members。
长连接的起停不在这里 —— 那是集成层的事,由入口在提交之后做。不提交事务。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import FeishuBot, User
from app.domain.feishu import bindings, bots
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def _bot(db: Session, bot_id: str) -> FeishuBot:
    bot = db.get(FeishuBot, bot_id)
    if bot is None:
        raise NotVisible("Not found")
    return bot


def readable_bot(db: Session, user: User, bot_id: str) -> FeishuBot:
    bot = _bot(db, bot_id)
    ensure_workspace_access(db, user, bot.workspace_id)
    return bot


def editable_bot(db: Session, user: User, bot_id: str) -> FeishuBot:
    bot = _bot(db, bot_id)
    ensure_workspace_perm(db, user, bot.workspace_id, "edit")
    return bot


def ensure_can_browse(db: Session, user: User, workspace_id: str) -> None:
    ensure_workspace_access(db, user, workspace_id)


def ensure_can_edit(db: Session, user: User, workspace_id: str) -> None:
    ensure_workspace_perm(db, user, workspace_id, "edit")


# ---------------- 机器人 ----------------


def list_bots(db: Session, user: User, workspace_id: str) -> list[FeishuBot]:
    ensure_workspace_access(db, user, workspace_id)
    return bots.list_bots(db, workspace_id)


def create_bot(db: Session, user: User, workspace_id: str, **fields: Any) -> FeishuBot:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return bots.create_bot(db, workspace_id=workspace_id, **fields)


def update_bot(db: Session, user: User, bot_id: str, changes: dict[str, Any]) -> FeishuBot:
    bot = editable_bot(db, user, bot_id)
    bots.update_bot(db, bot, changes)
    return bot


def delete_bot(db: Session, user: User, bot_id: str) -> FeishuBot:
    bot = editable_bot(db, user, bot_id)
    bots.delete_bot(db, bot)
    return bot


# ---------------- 绑定 ----------------


def issue_bind_code(db: Session, user: User, bot_id: str) -> tuple[str, datetime]:
    """成员给**自己**生成一次性绑定码,再从飞书发给机器人;之后机器人以这个成员的权限行事。"""
    bot = editable_bot(db, user, bot_id)
    return bindings.issue_bind_code(db, bot.workspace_id, user.id)


def list_bindings(db: Session, user: User, bot_id: str) -> list[bindings.Binding]:
    """**这台机器人的**绑定(外加说不清归属的老行,见 bindings.list_bindings)。

    此前这里只拿 `bot_id` 推 `workspace_id`,列的是整个工作区的绑定 —— 新机器人的面板里显示着
    别台机器人的绑定,看着就像"创建完自动绑定了"(而数据其实一行都没动)。
    """
    bot = readable_bot(db, user, bot_id)
    return bindings.list_bindings(db, bot.workspace_id, bot.id)


def remove_binding(db: Session, user: User, bot_id: str, open_id: str) -> None:
    """管谁能驱动机器人 = 成员管理。**只删这台机器人的那一行** —— 此前按工作区删,拿 A 的 URL
    能把 B 的绑定删掉。"""
    bot = _bot(db, bot_id)
    ensure_workspace_perm(db, user, bot.workspace_id, "members")
    bindings.remove_binding(db, bot.workspace_id, bot.id, open_id)
