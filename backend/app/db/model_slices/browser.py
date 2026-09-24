"""Browser automation domain ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class BrowserProfile(Base):
    """Reusable persistent browser identity: partition, proxy and metadata."""

    __tablename__ = "browser_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    partition: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    proxy: Mapped[str | None] = mapped_column(String(300), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 通用档案下次从哪一页开:上次收起内嵌浏览器时停在的地址(没收起过就是第一次输入的那个)。
    #: 通用档案就是一个**可持久化的浏览器会话** —— 认不出任何站点的登录态,所以卡片不谈「登没
    #: 登录」,只管「回到上次那一页」。发布账号的档案不用它。
    start_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class BrowserSession(Base):
    """One isolated browser automation session."""

    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ephemeral")
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    partition: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("browser_profiles.id", ondelete="SET NULL"), nullable=True
    )
    owner_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    owner_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    last_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class BrowserAction(Base):
    """One claimable action executed by the Electron browser worker."""

    __tablename__ = "browser_actions"
    __table_args__ = (Index("idx_browser_actions_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(ForeignKey("browser_sessions.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 认领它的执行器(ADR-0002 的三件套之一)。**必须跨重启稳定** —— 执行器重启后第一拍要
    #: 认出自己那些没跑完的动作并收回来,那是这个判据存在的全部理由。此前这一栏根本不存在:
    #: `claim_next_action(worker=...)` 收下了这个参数却**一次都没用过**,客户端发的也是字面量
    #: "browser" 而不是身份 —— 于是"这个执行器还在吗"这个问题在这条通道上没有答案。
    lease_worker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 这一次认领的凭据。回报时必须原样带回:老执行器的迟到回报会被它挡下来,
    #: 而不是覆盖掉新执行器正在干的那一份。
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 租约到点 = 认领它的那个执行器不在了。到点的动作判失败,可重试。
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
