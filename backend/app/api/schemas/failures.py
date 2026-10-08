"""一次失败给人看的三样 —— 全应用的失败展示读的都是这一份(前端 components/failure/FailureCard):

- `error_summary`:出了什么事,一句话(见 domain/failure_summary.summarize);
- `error_detail`:原文,比那一句多出信息时才有(detail_of);
- `error_hint`:认得出的原因和怎么修(hint_of),`{cause, steps: [{text, command}]}`。

都按**读的人**的语言出。任务、生成记录、发布记录、定时运行用 `FailureReadout` 加上这三格;画板格子另出一张表(BoardOut.failures)。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, computed_field

from app.api.schemas.base import ApiModel


class FailureStepOut(ApiModel):
    """修的一步:一句话;要在终端里敲的命令另放(原样,不翻)—— 失败卡把它摆成等宽的一块、带复制。"""

    text: str = ""
    command: str | None = None


class FailureHintOut(ApiModel):
    """认得出的失败:为什么(`cause`,一句)和怎么修(`steps`,一步一句),按读的人的语言挑好(见 domain/failure_summary.hint_of)。"""

    cause: str | None = None
    steps: list[FailureStepOut] = Field(default_factory=list)


class FailureViewOut(ApiModel):
    """一处失败给人看的三样(画板格子那一张表里的一条)。"""

    error_summary: str | None = None
    error_detail: str | None = None
    error_hint: FailureHintOut | None = None


class FailureReadout:
    """给出口模型加上 `error_summary` / `error_detail` / `error_hint`。用它的模型要有 `error`(原文,可以已经按 key 译过);有文案 key
    的再有 `error_key` / `error_params`(发布记录、定时运行只有原文:那一句就是原文去掉套话、截到一句的样子)。没失败三格都是 None。"""

    def _failure(self) -> tuple[str, str, dict[str, Any]]:
        return (str(getattr(self, "error", "") or ""), str(getattr(self, "error_key", "") or ""),
                dict(getattr(self, "error_params", None) or {}))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_summary(self) -> str | None:
        """出了什么事,一句话(按请求方的语言):失败卡上最醒目的那一行,原文 `error` 在「详情」和「复制错误」里。"""
        error, key, params = self._failure()
        if not key and not error:
            return None
        from app.core.i18n import get_current_locale
        from app.domain.failure_summary import summarize

        return summarize(error, key, params, get_current_locale()) or None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_detail(self) -> str | None:
        """原文(上游 / 插件的原话),默认收起的「详情」里给;和那一句说的是同一件事、没有多出信息时是 None —— 不摆一个点开还是
        那句话的「详情」。"""
        error, key, params = self._failure()
        if not key and not error:
            return None
        from app.core.i18n import get_current_locale
        from app.domain.failure_summary import detail_of

        return detail_of(error, key, params, get_current_locale())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def error_hint(self) -> FailureHintOut | None:
        """认得出的原因和怎么修(插件或后端的失败归类说的),那一句下面摆。没有是 None。"""
        _, _, params = self._failure()
        if not params:
            return None
        from app.core.i18n import get_current_locale
        from app.domain.failure_summary import hint_of

        hint = hint_of(params, get_current_locale())
        return FailureHintOut.model_validate(hint) if hint else None


__all__ = ["FailureHintOut", "FailureReadout", "FailureStepOut", "FailureViewOut"]
