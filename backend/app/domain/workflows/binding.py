"""节点输入绑定:数据边取值 + config 插值。

引擎(engine.py)和循环体子图(executors/loops.py)对节点输入的处理必须完全一致,
这份一致性以前靠两处内联代码保持——现在收敛到这里,成为唯一实现。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows import interpolate

# Loop nodes carry config that references the loop scope / body nodes ({{loop.*}}, {{body_node.x}}),
# which must NOT be resolved at the outer scope — they're interpolated per-iteration inside the
# loop handler / run_subgraph. LOOP_RAW_KEYS are the config fields kept verbatim for that reason.
LOOP_TYPES = frozenset({"loop_foreach", "loop_while"})
LOOP_RAW_KEYS = ("body", "output", "condition")


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


def interpolate_node_config(
    node_type: str, config: dict[str, Any], context: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """按节点类型插值 config:循环节点的 body/output/condition 保留原文,其余全量插值。"""
    if node_type in LOOP_TYPES:
        raw = {key: config.pop(key, None) for key in LOOP_RAW_KEYS if key in config}
        config = interpolate(config, context)
        config.update(raw)
        return config
    return interpolate(config, context)
