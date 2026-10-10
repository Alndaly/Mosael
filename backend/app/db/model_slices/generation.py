"""生成:一次会话、其中的每次任务,以及产出的素材。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.db.model_base import new_id, now

class GeneratedAsset(Base):
    __tablename__ = "generated_assets"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class GenerationSession(Base):
    __tablename__ = "generation_sessions"
    __table_args__ = (
        Index("idx_generation_sessions_ws_updated", "workspace_id", "updated_at"),
        #: 「这个人在这一处的那条会话」按它找(ADR 0052 §2)
        Index("idx_generation_sessions_origin", "workspace_id", "owner_user_id", "origin_kind", "origin_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 谁的(见 domain/sharing)。生成会话和对话一样是**某人的私人工作线程**,默认只有自己看得见。
    owner_user_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新生成")
    #: 收在哪个分组里(SessionGroup.kind == "generation")。和对话同一条规矩:不设外键,
    #: 分组被删时由 domain/session_groups 显式清空 —— 收纳方式不该反过来决定会话的生死。
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    #: 出处(ADR 0052,见 domain/generation/origins):这条会话是在哪一处开出来的 —— 和智能体对话的「家」同一个形状(种类 + id),
    #: 建的那一刻定、之后不变。`studio` 是创作页自己开的(id 为空);别处(画板、工作流、资产、定时任务、智能体对话、ComfyUI
    #: 工作台)一处一条,同一个人在同一处的生成都进这一条。不设外键:一列指几种表,而且要的正是「东西删了,会话照旧」。
    #: 库里也带默认值:老迁移里直接写 SQL 建会话的那几处(ADR 0055 并进来的「以前的…」)不写这两列。
    origin_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="studio", server_default="studio")
    origin_id: Mapped[str] = mapped_column(String(700), nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    generations: Mapped[list["GenerationJob"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="GenerationJob.id"
    )


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("generation_sessions.id", ondelete="CASCADE"), nullable=True
    )
    # SET NULL 而非 CASCADE:生成记录是创作历史,不能陪着任务中心的「清空已完成」
    # 一起蒸发(曾经就是这么丢的)。job 没了记录仍在,状态由 result_asset_id 兜底。
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    provider_profile_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("provider_profiles.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    #: 产出那份素材被删了(assets.delete_asset 记的):SET NULL 之后,没有这一笔的话这条生成和「还在排队」
    #: 长得一模一样 —— 没结果、没失败、任务行也没了。有它,界面才说得出「这份产出已被删除」。
    result_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 失败原因,和 Job 的那三列同形(`blame` 的产物:原话 + 文案 key + 参数,读的时候按读的人的语言翻)。
    #: 任务落「失败」时由 generation.runner.record_failure 抄过来 —— 任务会被「清空已结束」删掉,记录不会。
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_key: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    error_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)

    session: Mapped[GenerationSession | None] = relationship(back_populates="generations")
