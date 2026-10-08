from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.jobs import JobOut


class ScheduledTaskCreate(ApiModel):
    workspace_id: str
    project_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    kind: str = Field(min_length=1, max_length=60)
    trigger_type: str = Field(pattern="^(manual|once|interval|daily|weekly|webhook)$")
    schedule: dict = Field(default_factory=dict)
    timezone: str = Field(default="UTC", max_length=80)
    enabled: bool = True
    payload: dict = Field(default_factory=dict)


class ScheduledTaskUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    trigger_type: str | None = Field(default=None, pattern="^(manual|once|interval|daily|weekly|webhook)$")
    schedule: dict | None = None
    timezone: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None
    payload: dict | None = None


class ScheduledTaskOut(OrmModel):
    id: str
    workspace_id: str
    project_id: str | None
    name: str
    kind: str
    trigger_type: str
    schedule: dict
    timezone: str
    enabled: bool
    payload: dict
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # 归属(见 domain/sharing):是不是我的、在不在这个工作区里。定时任务默认共享,但仍有主人 ——
    # 事后要知道这段自动化是谁挂上去的。
    owner_user_id: str | None = None
    is_mine: bool = True
    shared: bool = True
    #: webhook 触发密钥是什么时候生成 / 重置的。webhook 任务上为空 = 只存哈希之前的那一把,它曾经对工作区里
    #: 所有人可见,界面提醒主人重置一次。
    webhook_secret_set_at: datetime | None = None
    #: 触发密钥的**原文**:只在生成它的那一次响应里有(建 webhook 任务、重置密钥、改成 webhook),别的时候都是 None ——
    #: 库里只存哈希(见 domain/scheduler.issue_webhook_secret)。
    webhook_secret: str | None = None


class ScheduledTaskRunOut(OrmModel):
    id: str
    scheduled_task_id: str
    job_id: str | None
    status: str
    result: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunScheduledTaskResponse(ApiModel):
    task: ScheduledTaskOut
    run: ScheduledTaskRunOut
    job: JobOut
