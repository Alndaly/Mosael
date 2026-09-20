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
    """Binds a Feishu sender (open_id) to a Mosael account within a workspace, so the bot
    acts with THAT member's permissions instead of a blanket owner identity."""

    __tablename__ = "feishu_bindings"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
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
