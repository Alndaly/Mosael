"""飞书接入:机器人、群与工作区的绑定,以及绑定用的一次性码。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.core.secrets_at_rest import EncryptedText
from app.db.model_base import new_id, now

class FeishuBot(Base):
    __tablename__ = "feishu_bots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="Mosael 助手")
    app_id: Mapped[str] = mapped_column(String(120), nullable=False)
    app_secret: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    capability: Mapped[str] = mapped_column(String(24), nullable=False, default="editor")  # readonly|editor|full
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="offline")  # offline|connecting|online|error
    status_detail: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class FeishuBinding(Base):
    """Binds a Feishu sender (open_id) to a Mosael account within a workspace **and an app**, so the bot
    acts with THAT member's permissions instead of a blanket owner identity.

    **键上必须有 `bot_id`(哪台机器人 = 哪个飞书应用)。** 飞书的 `open_id` 按应用隔离 —— 官方
    《用户身份概述》的原话是「不要在跨应用的数据通信中使用 open_id」。键只有
    `(workspace_id, open_id)` 时:同一台机器人换过应用之后,旧行的 open_id 永远匹配不上新事件的
    `sender_open_id`(机器人回「你还没有绑定」,而设置页照样显示已绑定);同一个人在两个应用里是
    两行,`requester_binding` 取哪一行由存储顺序定 —— 拿 A 的 open_id 用 B 的 token 发,飞书直接拒。

    **`bot_id` 指着 `feishu_bots` 并 `ON DELETE CASCADE`**:机器人没了,它名下的绑定一起走 ——
    那台应用眼里的 open_id 不再有任何应用解释得了,留着就是一行谁都匹配不上的死行。
    「谁曾绑过」不是这张**活跃**表的事(真要留痕是另一张审计 / 事件表的事)。
    """

    __tablename__ = "feishu_bindings"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    #: 这条绑定是**哪台机器人(哪个飞书应用)**眼里的 open_id。键的正式一员(理由见类说明)。
    bot_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("feishu_bots.id", ondelete="CASCADE"), primary_key=True
    )
    open_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class FeishuBindCode(Base):
    """One-time code a member issues in-app and sends to the bot from Feishu to bind their open_id."""

    __tablename__ = "feishu_bind_codes"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
