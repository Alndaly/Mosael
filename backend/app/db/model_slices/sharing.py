"""把一份资源共享给别人 —— 一张表管所有可共享的东西(会话、档案、发布账号…)。

resource_id 是**多态引用**:同一列指向五张表,所以建不了外键、也没有级联,删除路径要自己清
(见 domain/sharing 与 _cleanup_orphan_resource_shares)。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.db.model_base import new_id, now

class ResourceShare(Base):
    """主人把某样东西放进了某个工作区。**归属与共享是两件事**(见 domain/sharing)。

    此前只有归属这一半的位置(`workspace_id`),而它同时兼任了共享 —— 于是没有「放进来但仍然是
    我的」这种状态,某人的平台登录态、已登录的浏览器、私人对话全都是工作区的公共资产。
    """

    __tablename__ = "resource_shares"
    __table_args__ = (
        UniqueConstraint("kind", "resource_id", "workspace_id", name="uq_resource_share"),
        Index("idx_resource_shares_lookup", "kind", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    #: publish_account / browser_profile / agent_session / scheduled_task(见 domain/sharing.KINDS)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    shared_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
