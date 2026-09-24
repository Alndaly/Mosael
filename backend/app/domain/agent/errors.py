"""确认卡这条路上的领域异常。单独一个模块,好让工具模块和内核互相不依赖。"""

from __future__ import annotations

from app.core.i18n import LocalizedError


class ConfirmationError(LocalizedError, ValueError):
    """开卡校验或执行没过。带文案 key(`confirmErr_*`),`str(exc)` 按当时的语言翻;
    认不出的 key 当一句现成的话原样显示(上游原文就这么传)。"""
