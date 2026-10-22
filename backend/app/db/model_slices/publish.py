"""Publishing domain ORM models.

Callers keep importing from ``app.db.models``. This slice gives the publishing domain locality
without turning physical file names into a second public interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, text
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    @property
    def config_unreadable(self) -> bool:
        """落盘加密的设置解不开了(主密钥换了或丢了,见 core/secrets_at_rest):读出来是 None。"""
        return self.config is None


class PublishTask(Base):
    """One publishing attempt backed by a job on the task bus."""

    __tablename__ = "publish_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[str] = mapped_column(ForeignKey("publish_accounts.id", ondelete="CASCADE"), nullable=False)
    #: 发的是哪份素材。**素材删了,发布记录留着**(`SET NULL`):平台上的作品还在,作品 ID(`post`)是之后查播放、评论的
    #: 唯一线索。此前是 CASCADE —— 删一份发过的成片腾空间,发布历史和作品 ID 跟着没了。素材名记在 `asset_name` 里,
    #: 素材没了也说得出发的是什么。
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    asset_name: Mapped[str] = mapped_column(String(400), nullable=False, default="", server_default="")
    #: 这一条发的是**什么形状**(ADR 0076):video / image-text / article。默认 video,
    #: 老数据不用迁移;读的一侧也要按默认值兜底。
    content_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="video", server_default="video")
    #: 图文 / 文章的多份素材(按顺序);`asset_id` 仍写第一份,老读者不用改。
    #: 空数组 = 老任务,读的一侧回退到 `[asset_id]`。
    #: `server_default` 不是装饰:老库升级时「重建表再搬列」的那条迁移只搬旧列,
    #: 缺的列靠 SQL 默认值补 —— 没有它,一行老数据都搬不进去。
    asset_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    #: 正文 / 长文。以前正文塞在 `options.description` 里 —— 那是「发布选项」混进了「内容」,这里归位。
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    #: 图片顺序之外的附加信息(alt / 说明),平台支持时用。
    media_meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    short_title: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 发出去的**那一条作品**:平台上的作品 ID、链接、发布时间(形状见 domain/publish/post.py)。
    #: 发成功才有,否则是空 dict。后续要查这条作品的数据(TikHub 之类按作品 ID 取播放、评论),
    #: 靠的就是它 —— 发完不记,事后只能按标题去平台上猜是哪一条。
    post: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: 是哪个执行器认领的。**多执行器下,「孤儿任务」只能由认领它的那个来判** —— 那条判据是
    #: 「这个账号不在我当前在跑的集合里」,而这句话只有认领者说了才算数。别人拿自己的集合去判,
    #: 会把对方正在跑的任务判成中断(见 publish/worker.reclaim_orphaned_running)。
    #: 空串 = 老任务,或不报身份的执行器。
    claimed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)
