"""节点输入绑定:数据边取值 + config 插值。

引擎(engine.py)和循环体子图(executors/loops.py)对节点输入的处理必须完全一致,
这份一致性以前靠两处内联代码保持——现在收敛到这里,成为唯一实现。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows import NESTED_BODY_RAW_KEYS, NESTED_BODY_TYPES, interpolate

# 内嵌子图的节点(循环体、subgraph)的 body/output/condition 引用的是**子作用域 / 子图内部节点**
# ({{loop.*}}、{{input.*}}、{{body_node.x}}),绝不能在外层作用域解析——它们要留到执行器里对
# 子上下文插值(循环每迭代一次、subgraph 跑完一次)。NESTED_BODY_RAW_KEYS 就是为此保留原文的字段。
# condition 只有 loop_while 用;subgraph 没有,列表里多一个键只是「存在才 pop」,无副作用。
# 类型集合与保留键的单一真源在 app.domain.workflows(校验时的「不下钻」也复用同一份)。


def apply_data_edges(
    node_id: str,
    config: dict[str, Any],
    edges: list[dict[str, Any]],
    context: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """数据边(kind="data")把上游输出值绑到目标输入,优先于字面量 / 内联 {{var}}。
    上游已执行(数据边同时是排序约束)才有值;拿不到就跳过、保留原字面量。"""
    for edge in edges:
        if str(edge.get("kind", "")) != "data" or str(edge.get("target", "")) != node_id:
            continue
        source = str(edge.get("source", ""))
        output = str(edge.get("source_output", ""))
        target_input = str(edge.get("target_input", ""))
        if target_input and source in context and output in context[source]:
            config[target_input] = context[source][output]
    return config


def check_number_fields(node_type: str, config: dict[str, Any]) -> dict[str, Any]:
    """声明成数字(`"type": "number"`)的字段,插值、绑定之后必须真是数字 —— 或者留空。

    **按声明查一遍,所有节点一条规矩。** 此前各执行体自己 `float(config.get(...))`:语速填了
    「快一点」、或者一个引用落成了一段文字,抛出来的是 `could not convert string to float` ——
    没有 key、只有英文、也不说是哪一格。留空不归这里管:没填是合法的,缺省值是节点自己的事。
    """
    from app.domain.workflows import NODE_TYPES, WorkflowDomainError, field_name

    fields = (NODE_TYPES.get(node_type) or {}).get("config") or {}
    for key, spec in fields.items():
        if spec.get("type") != "number" or key not in config:
            continue
        value = config[key]
        if value is None or isinstance(value, (int, float)):
            continue
        if isinstance(value, str):
            if not value.strip():
                continue
            try:
                float(value)
                continue
            except ValueError:
                pass
        raise WorkflowDomainError("wfErr_mustBeNumber", params={"field": field_name(key, spec)})
    return config


def interpolate_node_config(
    node_type: str, config: dict[str, Any], context: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """按节点类型插值 config:内嵌子图节点(循环体 / subgraph)的 body/output/condition 保留原文,其余全量插值。"""
    if node_type in NESTED_BODY_TYPES:
        raw = {key: config.pop(key, None) for key in NESTED_BODY_RAW_KEYS if key in config}
        config = interpolate(config, context)
        config.update(raw)
        return config
    return interpolate(config, context)
