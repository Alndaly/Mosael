"""Task-bus request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, ValidationInfo, computed_field, field_validator

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


class ClearFinishedPreviewOut(ApiModel):
    """「清空已结束」删之前给人看的那几个数(见 domain/job_center.preview_clear_finished)。"""

    #: 会删掉几条(面板上的顶层任务)。
    tasks: int
    #: 连同收纳的子任务一共几个任务。
    jobs: int
    #: 这几条里有几条是工作区里别的成员发起的。
    by_others: int
    #: 已结束却留下的几条:工作流的运行记录、记过用量的任务。
    kept: int


class TaskEventOut(OrmModel):
    id: str
    job_id: str
    type: str
    payload: dict
    created_at: datetime


class JobSummaryOut(OrmModel):
    """任务列表里的一行:除了 `result` 什么都有(`JobOut` 是它加上 `result`)。**message 在这里按请求方的语言翻**。

    结果只在详情里给(`GET /api/jobs/{id}`)。工作流任务的 `result` 是整次运行的上下文,一条几十到几百 KB:维护者库里
    578 个顶层任务的列表 2.4 MB,其中 3 MB 量级的是工作流的结果 —— 而列表一处都不读它,有任务在跑时却每 1.5 秒拉一遍。

    翻译放在序列化这一层,而不是十二个返回 JobOut 的路由里各翻一次 —— 那是同一个问题十二个答案,
    漏一个,那一屏的任务就还是另一种语言。语言由中间件放进 ContextVar(见 core/i18n)。

    没有 key 的是一句现成的话(子任务转述的消息、第三方的原话),原样返回 —— 我们翻不了它。
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
    #: 同 message_key/params:只为翻译服务,必须声明在 error 之前。
    error_key: str = Field(default="", exclude=True)
    error_params: dict = Field(default_factory=dict, exclude=True)
    error: str | None
    created_at: datetime
    updated_at: datetime

    #: 库里取消落的是 `status=failed` + `jobErr_cancelled`(见 domain/jobs._cancel_job_row)。任务中心此前只看 status,
    #: 用户亲手点的「停止」原位写着「已停止」,右下角却弹红色的「失败」。这一位替它说,不把内部的文案 key 交出去;
    #: 真正的 cancelled 终态是另一件事(要迁移,待 ADR)。
    @computed_field  # type: ignore[prop-decorator]
    @property
    def cancelled(self) -> bool:
        """被停下的任务(取消 / 停止 / 上游停下连带),不是失败。status 仍是 failed。"""
        from app.domain.jobs import CANCELLED_ERROR_KEY

        return self.status == "failed" and self.error_key == CANCELLED_ERROR_KEY

    @field_validator("payload", mode="before")
    @classmethod
    def _without_workbench_graph(cls, value: object) -> object:
        """工作台跑画布上那张图时,图本身放在任务载荷里交给执行器(ADR 0038 §6,见 generation.operations.WORKBENCH_GRAPH):
        几百 KB,任务中心、画板、工作台都不读它 —— 出口不带。"""
        if isinstance(value, dict) and "workbench_graph" in value:
            return {key: item for key, item in value.items() if key != "workbench_graph"}
        return value

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
        """失败原因同样按请求方的语言翻。没有 key 的(第三方原话)原样返回。"""
        return _rendered(value, info, "error_key", "error_params")


class JobOut(JobSummaryOut):
    """一个任务的全部:列表里那一行,加上它做出了什么(`result`)。详情、取消、子任务这些一次只出几个的出口用它。"""

    result: dict


def _rendered(value: object, info: ValidationInfo, key_field: str, params_field: str) -> object:
    from app.core.i18n import get_current_locale, render_message

    data = info.data if isinstance(info.data, dict) else {}
    key = data.get(key_field) or ""
    #: key 列里只会是文案 key 或空(写入端由 core/i18n.is_message_key 把关,旧数据由迁移
    #: _migrate_job_keys_are_keys 改过),所以这里不再为"认不出的 key"留分支。
    if not key:
        return value
    return render_message(key, get_current_locale(), data.get(params_field) or {})
