"""Task-bus request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator

from app.api.schemas.base import ApiModel, OrmModel


class JobKindOut(ApiModel):
    """一种任务在界面上的样子(见 app/domain/job_catalog.py)。label 已按请求方的语言翻好。"""

    kind: str
    label: str
    announce: Literal["always", "failures", "never"]
    affects: list[str]
    view: str | None = None
    record_field: str | None = None


class JobKindCatalogOut(ApiModel):
    kinds: list[JobKindOut]
    #: 目录里没有的种类按这一条显示。
    fallback: JobKindOut


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
    #: 同 message_key/params:只为翻译服务,必须声明在 error 之前。
    error_key: str = Field(default="", exclude=True)
    error_params: dict = Field(default_factory=dict, exclude=True)
    error: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("message_key", "error_key", mode="before")
    @classmethod
    def _key_or_empty(cls, value: object) -> object:
        """还没落库的 Job 对象上这两列是 None(列默认值要 flush 之后才生效)。"""
        return value or ""

    @field_validator("message_params", "error_params", mode="before")
    @classmethod
    def _params_or_empty(cls, value: object) -> object:
        return value or {}

    @field_validator("message", mode="before")
    @classmethod
    def _translate(cls, value: object, info: ValidationInfo) -> object:
        return _rendered(value, info, "message_key", "message_params")

    @field_validator("error", mode="before")
    @classmethod
    def _translate_error(cls, value: object, info: ValidationInfo) -> object:
        """失败原因同样按请求方的语言翻。老任务只留下了当年那句话,原样返回。"""
        return _rendered(value, info, "error_key", "error_params")


def _rendered(value: object, info: ValidationInfo, key_field: str, params_field: str) -> object:
    from app.core.i18n import get_current_locale, render_message

    data = info.data if isinstance(info.data, dict) else {}
    key = data.get(key_field) or ""
    if not key:
        return value
    return render_message(key, get_current_locale(), data.get(params_field) or {})
