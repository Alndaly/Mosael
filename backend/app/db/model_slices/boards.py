from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class Board(Base):
    """创意画板；canvas 的结构和状态迁移由 ``app.domain.boards`` 负责。"""

    __tablename__ = "boards"
    __table_args__ = (Index("idx_boards_workspace_updated", "workspace_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    canvas: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: 客户端写入时携带的乐观并发令牌。它描述当前投影，不是历史版本号；每次成功写入加一。
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
