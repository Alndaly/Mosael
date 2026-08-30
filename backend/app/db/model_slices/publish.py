"""Publishing domain ORM models.

Callers keep importing from ``app.db.models``. This slice gives the publishing domain locality
without turning physical file names into a second public interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.secrets_at_rest import EncryptedJSON
from app.db.model_base import new_id, now


class PublishAccount(Base):
    """A publishing identity; ``platform`` selects the Electron Adapter."""

    __tablename__ = "publish_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("browser_profiles.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    proxy: Mapped[str | None] = mapped_column(String(300), nullable=True)
    binding_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    profile_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)


class PublishTask(Base):
    """One publishing attempt backed by a job on the task bus."""

    __tablename__ = "publish_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("publish_accounts.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    short_title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
