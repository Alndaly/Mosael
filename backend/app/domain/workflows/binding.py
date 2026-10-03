"""节点输入绑定:数据边取值 + config 插值。

引擎(engine.py)和循环体子图(executors/loops.py)对节点输入的处理必须完全一致,
这份一致性以前靠两处内联代码保持——现在收敛到这里,成为唯一实现。
"""

from __future__ import annotations

from typing import Any

from app.domain.workflows import NESTED_BODY_RAW_KEYS, NESTED_BODY_TYPES, interpolate
from app.domain.workflows.graph_rules import interpolate_json_text

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
    上游已执行(数据边同时是排序约束)才有值;拿不到就跳过、保留原字面量。

    **在插值之后调用,绑上来的值不再参与插值。** 上游的值是数据,不是模板:此前先绑后插值,
    一段 LLM 回答、一段抓回来的网页里恰好写着 `{{start.api_key}}`,就会在下游被换成开始节点
    的那个值(或被吞成空串)。规范化把每一个精确引用都升级成了数据边,所以几乎所有绑定都走
    这里。组合模板「前缀{{llm.text}}」的插值本来就只替换一趟(re.sub 不回扫替换进去的文字),
    两种写法由此一致:上游的值在任何一条路上都不再被当成模板。
    """
    for edge in edges:
        if str(edge.get("kind", "")) != "data" or str(edge.get("target", "")) != node_id:
            continue
        source = str(edge.get("source", ""))
        output = str(edge.get("source_output", ""))
        target_input = str(edge.get("target_input", ""))
        value = _path_value(context.get(source), output)
        if target_input and value is not _MISSING:
            _set_existing_path(config, target_input, value)
    return config


_MISSING = object()


def _path_value(value: Any, path: str) -> Any:
    """数据端口允许指向结构化输出里的叶子，例如 ``output.note_id``。"""
    current = value
    for part in path.split("."):
        if not part or not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_existing_path(config: dict[str, Any], path: str, value: Any) -> None:
    """写已有的嵌套配置叶子；路径不存在时按旧契约写顶层键，兼容已保存的普通输入。"""
    parts = [part for part in path.split(".") if part]
    current: Any = config
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current or not isinstance(current[part], dict):
            config[path] = value
            return
        current = current[part]
    if not parts or not isinstance(current, dict) or parts[-1] not in current:
        config[path] = value
        return
    current[parts[-1]] = value


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
    """按节点类型插值 config:内嵌子图节点(循环体 / subgraph)的 body/output/condition 保留原文;
    **代码字段(`"type": "code"`)也保留原文**;声明了 `"interpolate": "json"` 的字段按 JSON 的规矩插值
    (见 interpolate_json_text);其余全量插值。

    代码字段不插值:`{{上游.输出}}` 是按文字拼进代码的,上游交来一段带引号的文字就能改写整段脚本
    (「执行脚本」在用户已登录的网页里跑)。上游的值走节点的入参(`input`),作为数据交进去。
    """
    from app.domain.workflows import NODE_TYPES

    specs = (NODE_TYPES.get(node_type) or {}).get("config") or {}
    as_json = {
        key: config.pop(key)
        for key, spec in specs.items()
        if isinstance(spec, dict) and spec.get("interpolate") == "json" and isinstance(config.get(key), str)
    }
    kept = set(NESTED_BODY_RAW_KEYS) if node_type in NESTED_BODY_TYPES else set()
    kept |= {key for key, spec in specs.items() if isinstance(spec, dict) and spec.get("type") == "code"}
    raw = {key: config.pop(key) for key in list(config) if key in kept}
    config = interpolate(config, context)
    config.update(raw)
    config.update({key: interpolate_json_text(value, context) for key, value in as_json.items()})
    return config
