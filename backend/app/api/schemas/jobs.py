"""Task-bus request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, ValidationInfo, field_validator

from app.api.schemas.base import OrmModel


class TaskEventOut(OrmModel):
    id: str
    job_id: str
    type: str
    payload: dict
    created_at: datetime


class JobOut(OrmModel):
    """任务出口。**message 在这里按请求方的语言翻**。

    翻译放在序列化这一层,而不是十二个返回 JobOut 的路由里各翻一次 —— 那是同一个问题十二个答案,
    漏一个,那一屏的任务就还是另一种语言。语言由中间件放进 ContextVar(见 core/i18n)。

    老任务没有 key(它们只留下了当年渲染的那句话),原样返回 —— 那是数据本身的界限。
    """

    id: str
    workspace_id: str
    kind: str
    parent_job_id: str | None = None
    status: str
    progress: float
    #: 这两个只为翻译服务,**必须声明在 message 之前** —— 校验器的 info.data 只含先于本字段
    #: 验证过的项,顺序反了就永远读不到 key。exclude 让它们不出现在响应里。
    message_key: str = Field(default="", exclude=True)
    message_params: dict = Field(default_factory=dict, exclude=True)
    message: str
    payload: dict
    result: dict
    error: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("message", mode="before")
    @classmethod
    def _translate(cls, value: object, info: ValidationInfo) -> object:
        from app.core.i18n import get_current_locale, t

        data = info.data if isinstance(info.data, dict) else {}
        key = data.get("message_key") or ""
        if not key:
            return value
        return t(key, get_current_locale(), **(data.get("message_params") or {}))
