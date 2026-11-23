"""插件交回来的目录(模型库、工作流库、参考库……)里一个字段**怎么读**:不信任它的类型与长度,读不出就当没有。

三个目录类能力(`model_library`、`server_workflows`、`reference_library`)此前各抄一份 `_text / _number`。
它们读的是同一种东西 —— 另一个进程交回来的 JSON —— 规矩就只该有一份。
"""

from __future__ import annotations

from typing import Any


def text(value: Any, limit: int = 500) -> str:
    """字符串去掉首尾空白、截到 `limit`;不是字符串就是空串(数字、布尔都不替它转)。"""
    return value.strip()[:limit] if isinstance(value, str) else ""


def number(value: Any) -> float | None:
    """数字就转成 float;布尔(Python 里也是 int)和别的一律当没有。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
