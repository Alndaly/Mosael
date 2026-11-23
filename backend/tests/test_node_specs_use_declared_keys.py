"""工作流节点定义只用 `node_spec` 里声明过的键 —— 打错一个键名不会报错,只会让界面上那一格默默不生效。

后端没有静态类型检查,`NodeSpec` / `FieldSpec` 两个 TypedDict 的约束由这条测试在运行时兑现。
"""

from __future__ import annotations

import pytest

from app.domain.workflows.node_spec import FieldSpec, NodeSpec
from app.domain.workflows.node_types import NODE_TYPES

NODE_KEYS = set(NodeSpec.__annotations__)
FIELD_KEYS = set(FieldSpec.__annotations__)


@pytest.mark.parametrize("name", sorted(NODE_TYPES))
def test_node_uses_only_declared_keys(name: str) -> None:
    node = NODE_TYPES[name]
    assert set(node) <= NODE_KEYS, f"{name} 用了没声明的节点键:{sorted(set(node) - NODE_KEYS)}"
    assert NodeSpec.__required_keys__ <= set(node), f"{name} 少了必填的键:{sorted(NodeSpec.__required_keys__ - set(node))}"
    for key, field in node["config"].items():
        assert set(field) <= FIELD_KEYS, f"{name}.{key} 用了没声明的字段键:{sorted(set(field) - FIELD_KEYS)}"
        assert "type" in field, f"{name}.{key} 没写 type"


def test_every_declared_key_is_used_somewhere() -> None:
    """声明了却没人用的键是死的说明:读的人会以为它有作用。"""
    used_node = {key for node in NODE_TYPES.values() for key in node}
    used_field = {key for node in NODE_TYPES.values() for field in node["config"].values() for key in field}
    assert NODE_KEYS - used_node == set()
    assert FIELD_KEYS - used_field == set()
