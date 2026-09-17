"""确认卡这条路上的领域异常。单独一个模块,好让工具模块和内核互相不依赖。"""

from __future__ import annotations


class ConfirmationError(ValueError):
    pass
