"""工作流配置字段的条件启用契约。

后端运行前校验与前端表单分别实现这一小段判断；两侧共同运行
``contracts/workflow-field-activation.json``，避免语义悄悄分叉。
"""

from __future__ import annotations

from typing import Any


def config_field_active(spec: dict[str, Any], config: dict[str, Any], specs: dict[str, Any]) -> bool:
    """字段是否参与当前节点配置。

    父字段**没填**时读取其声明默认值。「没填」和执行体是同一个意思:键不在、`null`、空串 ——
    执行体读到这三种都按缺省跑(`config.get(...) or 缺省`)。此前这里只认「键不在」,而前端
    的 `??` 认「键不在或 null」:一个存成 null 的父字段,表单说这一格该填,校验说不用填,
    运行时又按缺省跑。模板值要到运行时才能确定，因此保持字段启用，允许操作者配置所有
    可能会用到的分支。
    """
    conditions = spec.get("active_when")
    if not isinstance(conditions, dict):
        return True
    for key, expected in conditions.items():
        parent = specs.get(key) if isinstance(specs.get(key), dict) else {}
        actual = config.get(key)
        if actual is None or actual == "":
            actual = parent.get("default")
        if isinstance(actual, str) and "{{" in actual:
            continue
        allowed = expected if isinstance(expected, list) else [expected]
        if actual not in allowed:
            return False
    return True


__all__ = ["config_field_active"]
