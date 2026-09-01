"""Task-bus ORM models.

Callers keep importing from ``app.db.models``. The physical slice only gives the task bus
locality; it is not a second public interface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.db.model_base import new_id, now


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("idx_jobs_workspace_status_updated", "workspace_id", "status", "updated_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    #: 这活儿**替谁干**。后台线程手里只有一个 job:没有这一栏,它就答不出该用谁的钥匙、
    #: 花谁的额度,于是只能全体共用一把(见 domain/provider_credentials)。定时触发的任务
    #: 记的是挂它的那个人(ScheduledTask.owner_user_id)—— 定时执行没有"当时的操作人",
    #: 但一定有一个"当初挂上去的人"。
    created_by: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # 工作流节点派生的子任务(发布/导出/转写/生成/配音)挂在父工作流 job 上,任务中心据此收纳、
    # 不再与父工作流平铺成两行。顶层任务(用户直接发起)为 None。软引用,不设外键级联。
    parent_job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: 给人看的那句话。**它是渲染结果**(缺省语言),留着是因为不翻译的消费者也读它:
    #: 工作流把子任务的 message 拼进自己的错误里、日志、直接读库的运维脚本。
    message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    #: 同一句话的 key 与参数(见 core/i18n)。**接口按请求语言翻的是这两个**,message 只是兜底。
    #:
    #: 为什么不只存 key:这一列会**落库**,而任务记录活得比一次请求久。写入时就翻会把语言冻死在
    #: 那一刻 —— 用户切成英文之后,历史任务仍是中文,而那正是这次要修的毛病。
    #: 老行没有 key(它们只留下了当年渲染的那句话),接口照旧原样返回 message。
    message_key: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    message_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (Index("idx_task_events_job_created", "job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
