"""项目:工作区里的一个创作单元,素材和时间线挂在它下面。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.db.model_base import new_id, now

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("idx_projects_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    active_sequence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    sequences: Mapped[list["Sequence"]] = relationship(  # noqa: F821 —— 跨切片的关系由 SQLAlchemy
        # 按注册表里的类名解析,不需要 import;真去 import 就成了 projects ⇄ sequences 的循环。
        back_populates="project", cascade="all, delete-orphan")
