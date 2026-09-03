from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class Workflow(Base):
    """可执行工作流的当前投影；不可变历史由 :class:`WorkflowRevision` 持有。"""

    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class WorkflowRevision(Base):
    """工作流图的一份不可变快照。

    `Workflow.graph` 是读路径上的当前投影；这里才是历史与执行复现的事实来源。恢复旧图会
    追加新行，不修改任何已有修订。模板版本仍留在 graph.meta 中，它描述模板出处，不与用户
    每次保存产生的 revision 混为一谈。
    """

    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "revision", name="uq_workflow_revisions_workflow_revision"),
        Index("idx_workflow_revisions_workflow_revision", "workflow_id", "revision"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    graph: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="edit", server_default="edit")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
