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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
