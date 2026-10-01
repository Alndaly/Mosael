"""整数格的解析:一格整数怎么读、下限怎么说。不碰引擎、不碰数据库 —— 笔记节点这类不在 engine⇄executors
环里的执行器也能用(见 tests/test_import_layering 的 LAZY_CYCLE_MODULES)。"""

from __future__ import annotations

import math
from typing import Any

from app.domain.workflows import NODE_TYPES, WorkflowDomainError


def whole_number(config: dict[str, Any], key: str, *, node_type: str, default: int | None = None) -> int | None:
    """一格整数:留空是 `default`;`10`、`"10"`、`"10.0"`、`10.0` 都是 10;`"10.5"`、`"很多"` 报「必须是整数」,说是哪一格。

    数字格插值、绑定之后常常是 `"10.0"`(上游算出来的数、JSON 里的浮点)。此前各执行体各写一句
    `int(config.get(...))`:`"10.0"` 抛一句英文的 `invalid literal for int()`、不说是哪一格;有的
    干脆 except 掉,悄悄换成默认值 —— 填了 0 或 "10.0" 的人以为自己设了,其实跑的是 50。
    """
    from app.domain.workflows import field_name

    raw = config.get(key)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    number: float | None
    try:
        number = None if isinstance(raw, bool) else float(str(raw).strip())
    except ValueError:
        number = None
    if number is None or not math.isfinite(number) or not number.is_integer():
        spec = ((NODE_TYPES.get(node_type) or {}).get("config") or {}).get(key)
        raise WorkflowDomainError("wfErr_mustBeInteger", params={"field": field_name(key, spec)})
    return int(number)


def at_least(value: int, minimum: int, *, key: str, node_type: str) -> int:
    """整数格的下限:不够就说是哪一格、最少多少(而不是悄悄换成默认值)。"""
    from app.domain.workflows import field_name

    if value < minimum:
        spec = ((NODE_TYPES.get(node_type) or {}).get("config") or {}).get(key)
        raise WorkflowDomainError("wfErr_belowMin", params={"field": field_name(key, spec), "min": minimum})
    return value
