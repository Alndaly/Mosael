"""工作流配置字段的条件启用契约。

后端运行前校验与前端表单分别实现这一小段判断；两侧共同运行
``contracts/workflow-field-activation.json``，避免语义悄悄分叉。
"""

from __future__ import annotations

from typing import Any


def config_field_active(spec: dict[str, Any], config: dict[str, Any], specs: dict[str, Any]) -> bool:
    """字段是否参与当前节点配置。

    父字段没显式保存时读取其声明默认值。模板值要到运行时才能确定，因此保持字段启用，允许
    操作者配置所有可能会用到的分支。
    """
    conditions = spec.get("active_when")
    if not isinstance(conditions, dict):
        return True
    for key, expected in conditions.items():
        parent = specs.get(key) if isinstance(specs.get(key), dict) else {}
        actual = config.get(key, parent.get("default"))
        if isinstance(actual, str) and "{{" in actual:
            continue
        allowed = expected if isinstance(expected, list) else [expected]
        if actual not in allowed:
            return False
    return True


__all__ = ["config_field_active"]
