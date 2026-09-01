from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel
from app.api.schemas.jobs import JobOut


class ScheduledTaskCreate(BaseModel):
    workspace_id: str
    project_id: str | None = None
    name: str = Field(min_length=1, max_length=180)
    kind: str = Field(min_length=1, max_length=60)
    trigger_type: str = Field(pattern="^(manual|once|interval|daily|weekly|webhook)$")
    schedule: dict = Field(default_factory=dict)
    timezone: str = Field(default="UTC", max_length=80)
    enabled: bool = True
    payload: dict = Field(default_factory=dict)


class ScheduledTaskUpdate(BaseModel):
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


class ScheduledTaskRunOut(OrmModel):
    id: str
    scheduled_task_id: str
    job_id: str | None
    status: str
    result: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunScheduledTaskResponse(BaseModel):
    task: ScheduledTaskOut
    run: ScheduledTaskRunOut
    job: JobOut
