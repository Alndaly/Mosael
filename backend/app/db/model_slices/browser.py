"""Browser automation domain ORM models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, text
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
    #: 一份登录(分区)同一时刻最多一个开着的具名 / 池档案会话 —— 租约落在库里,而不是只靠「先查后建」:
    #: 同一拍的两次打开都查到「没有」,各建一个(见 domain/browser 的 _lease_login)。临时会话各有各的分区,不在其列。
    __table_args__ = (
        Index(
            "uq_browser_sessions_open_login",
            "partition",
            unique=True,
            sqlite_where=text("status = 'open' AND kind IN ('named', 'profile')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ephemeral")
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    partition: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("browser_profiles.id", ondelete="SET NULL"), nullable=True
    )
    owner_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    #: owner_kind=workflow 时是**这次运行**的(最外层)工作流任务 id —— 运行落终态时它名下的
    #: 会话一并关掉(见 domain/browser 的 _close_run_sessions)。
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


class BrowserPartitionMove(Base):
    """一条登录分区的**搬家单**:后端算出来,Electron 在磁盘上执行。

    具名会话的分区名改过一次形状(旧:`persist:rpa-<清洗后的名字>`,跨工作区共用、非 ASCII 名字撞成一个;
    新:`persist:rpa-<工作区>-<名字哈希>`)。已经登录过的数据在 Electron 的 `userData/Partitions/<分区名>`
    目录里,后端既不知道那个目录在哪,也不该去碰它 —— 所以迁移只写下「谁搬到哪」,执行器启动时领走、
    搬完回报(见 electron/publish/partitionMoves.ts)。

    `status` 是迁移时定下的:pending(要搬)/ abandoned(不搬:这个旧分区也被别的工作区、别的名字用过,只归最早的
    那一个,原因写在 `reason`)。**搬没搬是每台电脑自己的事**,记在 BrowserPartitionMoveReceipt 上 —— 登录数据在
    各自的磁盘上,一台搬了不等于另一台也搬了。
    """

    __tablename__ = "browser_partition_moves"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    old_partition: Mapped[str] = mapped_column(String(120), nullable=False)
    new_partition: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    session_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class BrowserPartitionMoveReceipt(Base):
    """一台电脑(执行器)对一条搬家单的回执:在它的磁盘上搬了(done),或者没法搬(skipped,原因写在 `reason`)。

    此前搬家单只有一个全局状态,第一个连上来的执行器领走就落终态:旧目录不在它那台电脑上,就记一笔 skipped,
    真正有那份登录的另一台电脑再也领不到。现在每台各记各的;没有回执的那台下次启动接着看(旧目录不在、
    改名失败都不记回执 —— 前者以后可能从备份里回来,后者可能只是一时被占着)。
    """

    __tablename__ = "browser_partition_move_receipts"
    __table_args__ = (Index("uq_browser_partition_move_receipts", "move_id", "worker", unique=True),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    move_id: Mapped[str] = mapped_column(
        ForeignKey("browser_partition_moves.id", ondelete="CASCADE"), nullable=False
    )
    #: 执行器的身份(跨重启稳定,每台电脑一个,同 BrowserAction.lease_worker)。
    worker: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
