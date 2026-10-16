"""Canonical workflow graph shapes shared by every persistence entry point.

An exact ``{{node.output}}`` value is a data dependency, not a manually entered literal.  Keeping
it in ``config`` made resource fields render as workspace selectors and hid the real dependency
behind an ordinary control edge.  This module upgrades that unambiguous shorthand to the native
data-edge representation while leaving composite templates and nested output paths untouched.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from app.domain.workflows.graph_rules import NESTED_BODY_RAW_KEYS

PURE_REFERENCE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def normalize_graph(graph: dict[str, Any], *, node_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """**图的规范形状**:保存、导入、官方模板、迁移都经过这一个入口。

    三件事:声明为「行列表」的字段统一成列表(见 canonicalize_line_fields),声明为「一串」的字段
    存成「名字 → 值」对象的改成值的列表(见 canonicalize_list_fields),精确的 `{{节点.输出}}` 升级成
    数据边(见 canonicalize_data_bindings)。库里只存规范形状,读取端和编辑器因此只认一种。
    """
    lists = canonicalize_list_fields(canonicalize_line_fields(graph, node_types=node_types), node_types=node_types)
    return canonicalize_data_bindings(canonicalize_start_params(lists), node_types=node_types)


def canonicalize_start_params(graph: dict[str, Any]) -> dict[str, Any]:
    """开始节点的必填清单(`required_params`)只含 params 里有的参数,按参数的顺序,不重复。

    面板上必填是每一行自己的开关,改名、删行时跟着走(前端 StartParamsField);别的写入方(智能体、接口)写的
    清单在这里收拾:名字去两头空白、去掉空的和重复的;**点名了却没有那一行的补一行**(默认空着)—— 写的人要的是
    「这个参数跑之前必须有值」,补一行之后运行前照旧拦,面板上看得见;丢掉它就悄悄变成了可以不填。

    不是列表的不动(还写成一串字的,由校验说清形状,见 graph_rules._required_params_shape_errors)。开始节点只在顶层。
    """
    normalized = deepcopy(graph)
    for node in normalized.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start" and isinstance(node.get("config"), dict):
            node["config"] = param_options_as_rows(required_params_as_rows(node["config"]))
    return normalized


def param_options_as_rows(config: dict[str, Any]) -> dict[str, Any]:
    """选项参数(`param_options`)点名了却没有那一行的,补一行(默认空着)—— 和必填清单同一条:写的人要的是「这个参数
    只能从几项里选」,补一行之后面板上看得见、运行前照样按选项查。选项本身的形状由校验说(graph_rules)。"""
    declared = config.get("param_options")
    params = config.get("params")
    if not isinstance(declared, dict) or not isinstance(params, (dict, type(None))):
        return config
    rows = dict(params or {})
    for name in declared:
        if isinstance(name, str) and name.strip():
            rows.setdefault(name, "")
    return {**config, "params": rows}


def required_params_as_rows(config: dict[str, Any]) -> dict[str, Any]:
    """一个开始节点的配置,必填清单收拾成规范形状(见 canonicalize_start_params)。清单不是列表的原样交回。"""
    names = config.get("required_params")
    params = config.get("params")
    if not isinstance(names, list) or not isinstance(params, (dict, type(None))):
        return config
    wanted: list[str] = []
    for name in names:
        name = name.strip() if isinstance(name, str) else ""
        if name and name not in wanted:
            wanted.append(name)
    rows = dict(params or {})
    for name in wanted:
        rows.setdefault(name, "")
    return {**config, "params": rows, "required_params": [name for name in rows if name in wanted]}


def canonicalize_list_fields(graph: dict[str, Any], *, node_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """声明为「一串」(`"type": "list"`,插件节点的 JSON Schema 数组)的字段,存成了「名字 → 值」对象的,改成那些值的列表。

    节点表单此前把数组当对象,给的是映射编辑器,存下去的是 `{"a": "第一段", "b": "第二段"}` —— 交给插件的就
    不是数组。迁移只改得了它那一刻认得出的(要读插件报的工具清单),认不出的、导入的老文件、恢复的老修订还会
    带着它回来,所以这一步在规范化里:保存、导入、模板都走这里。

    哪一格是数组**看节点类型的声明**;声明拿不到(插件没装、工具没报出来)的节点原样不动,不猜。
    """
    normalized = deepcopy(graph)
    _lists_in(normalized, node_types)
    return normalized


def _lists_in(graph: dict[str, Any], node_types: dict[str, dict[str, Any]]) -> None:
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("config"), dict):
            continue
        config = node["config"]
        specs = (node_types.get(str(node.get("type", ""))) or {}).get("config") or {}
        for key, spec in specs.items():
            if isinstance(spec, dict) and spec.get("type") == "list" and isinstance(config.get(key), dict):
                config[key] = list(config[key].values())
        body = config.get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            _lists_in(body, node_types)


def canonicalize_line_fields(graph: dict[str, Any], *, node_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """声明了 `"lines": True` 的字段,值统一成**行的列表**(一段多行文本按行拆开)。

    为什么要是列表:某一行可以正好是一整串引用(`{{角色三视图.results}}`),插值后是一组值,
    解析时摊平 —— 全部角色的三视图一次接进参考图。存成一整段多行文本的话,这一行在插值时
    和别的行拼在同一个字符串里,列表被 `str()` 成 `['…', '…']`,当场就坏。
    """
    normalized = deepcopy(graph)
    _lines_in(normalized, node_types)
    return normalized


def _lines_in(graph: dict[str, Any], node_types: dict[str, dict[str, Any]]) -> None:
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        specs = (node_types.get(str(node.get("type", ""))) or {}).get("config") or {}
        for key, spec in specs.items():
            if isinstance(spec, dict) and spec.get("lines") and isinstance(config.get(key), str):
                config[key] = [line.strip() for line in config[key].splitlines() if line.strip()]
        body = config.get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            _lines_in(body, node_types)


def canonicalize_data_bindings(
    graph: dict[str, Any],
    *,
    node_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a copy with exact node-output references represented as typed data edges.

    Only a top-level scalar config value with exactly two path components is losslessly
    representable by the current edge contract.  ``{{node.json.items}}`` and strings that combine
    prose with references therefore stay as templates.  Nested workflow bodies are normalized by
    the same rules, in their own scope.
    """

    normalized = deepcopy(graph)
    _canonicalize_graph(normalized, node_types)
    return normalized


def _canonicalize_graph(graph: dict[str, Any], node_types: dict[str, dict[str, Any]]) -> None:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    # Validation owns malformed input.  Normalization must never make a broken payload valid by
    # silently dropping its bad members or inventing missing containers.
    if (
        not isinstance(nodes, list)
        or not isinstance(edges, list)
        or any(not isinstance(node, dict) for node in nodes)
        or any(not isinstance(edge, dict) for edge in edges)
    ):
        return

    by_id = {str(node.get("id", "")): node for node in nodes}
    bound_inputs = {
        (str(edge.get("target", "")), str(edge.get("target_input", ""))): edge
        for edge in edges
        if edge.get("kind") == "data" and edge.get("target_input")
    }
    inputs_by_target: dict[str, list[str]] = {}
    for target_id, input_key in bound_inputs:
        inputs_by_target.setdefault(target_id, []).append(input_key)
    new_bindings: list[tuple[str, str, str, str]] = []

    for target in nodes:
        target_id = str(target.get("id", ""))
        metadata = node_types.get(str(target.get("type", ""))) or {}
        config_specs = metadata.get("config") or {}
        config = target.get("config")
        if not target_id or not isinstance(config, dict) or not isinstance(config_specs, dict):
            continue

        raw_connected_inputs = target.get("inputs")
        connected_inputs = (
            [str(key) for key in raw_connected_inputs if str(key)]
            if isinstance(raw_connected_inputs, list)
            else []
        )
        for input_key in inputs_by_target.get(target_id, []):
            if input_key not in connected_inputs:
                connected_inputs.append(input_key)
        #: 内嵌子图节点的 body/output/condition 属于**体内**作用域(见 NESTED_BODY_RAW_KEYS):
        #: `{{llm-1.text}}` 指的是体里的 llm-1,不是外层那个。节点 id 只在当前这一层唯一,外层与体内
        #: 同名是常态 —— 此前这里把它升级成一条**来自外层**的数据边,output 被清空、loop_while 的
        #: 条件绑到了外层的值上。和 reference_dependencies、画布的 isNestedScopeConfig 同一条界线。
        inner_scope = NESTED_BODY_RAW_KEYS if metadata.get("body_scope") else ()
        for input_key, value in config.items():
            spec = config_specs.get(input_key)
            #: 代码字段里的 {{…}} 不是引用(它不插值,见 graph_rules.code_fields),不变成数据边。
            if not isinstance(spec, dict) or spec.get("type") in {"object", "graph", "code"} or input_key in inner_scope:
                continue
            if not isinstance(value, str):
                continue
            match = PURE_REFERENCE_RE.fullmatch(value.strip())
            if match is None:
                continue
            reference = match.group(1).split(".")
            if len(reference) != 2:
                continue
            source_id, source_output = reference
            source = by_id.get(source_id)
            source_metadata = node_types.get(str(source.get("type", ""))) if source else None
            outputs = source_metadata.get("outputs", []) if source_metadata else []
            if source_id == target_id or source_output not in outputs:
                continue

            binding_key = (target_id, input_key)
            if binding_key not in bound_inputs:
                new_bindings.append((source_id, source_output, target_id, input_key))
            if input_key not in connected_inputs:
                connected_inputs.append(input_key)
            config[input_key] = ""

        if connected_inputs:
            target["inputs"] = connected_inputs

        body = config.get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            _canonicalize_graph(body, node_types)

    #: **这里曾经折边,现在一条都不折(维护者 2026-10-16 的决定:"我要能看见,用方案一")。**
    #:
    #: 折的是「这一步刚从精确引用升级出来的数据边」造成的冗余:同一对节点间有数据边时,那条无 handle 的
    #: 控制边看起来只排先后(数据边也排先后)。可它折与不折**取决于巧合** —— `foldable_into` 要求「折掉后
    #: 谁该跑不变」,目标另有入边时就不折。最小复现:`start → A → T` 加一条 `T.body = {{B.text}}` 就有了
    #: B→T 的数据边,此时 A→T 折掉(T 只剩 B→T,「A 跑了才跑」变成「A 或 B 跑了就跑」);只要 T 再有**任何
    #: 一条**别的入边,同一条 A→T 就留下。同一张图里时有时无,作者画的那条线在不在全看别处的连线。
    #:
    #: 代价在官方模板上看得最清楚:15 张手写的图里 start→output 的控制链本来都完整(15/15),规范化折断了
    #: 其中 10 张 —— 68 条控制边被折、55 个节点只剩数据入边(画布上那一格没有线)。
    #:
    #: 当初敢折,是因为「引擎只看控制边」;可折掉的那几条**确实会改谁该跑** —— 目标上有带路由语义的
    #: 控制边(条件的真 / 假出口)时,那些**已经有一条同向数据线**的普通控制边本来就该只排先后,而引擎的
    #: 「任一条来源跑了就跑」不这么判。折边一直在替引擎模拟这条判法;不折之后,它由 engine.incoming_active
    #: 明说(ADR 0063)。于是「谁该跑」折与不折完全一样,而作者画出来的边一条不少。
    #: 保留下来的理由是**画布与库一致** —— 用户画出来的连线,就是这张图;少一条边,他看不见的先后就少一段。
    #: 见 docs/adr/0063-画出来的控制边一律保留.md。
    #:
    #: 注意:**精确引用升级成数据边本身**是另一件事,照旧(见本函数开头),别一起删。
    used_ids = {str(edge.get("id", "")) for edge in edges}
    for source_id, source_output, target_id, target_input in new_bindings:
        edge_id = f"d-{source_id}-{source_output}-{target_id}-{target_input}"
        if edge_id in used_ids:
            suffix = 2
            while f"{edge_id}-{suffix}" in used_ids:
                suffix += 1
            edge_id = f"{edge_id}-{suffix}"
        used_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "kind": "data",
                "source_output": source_output,
                "target_input": target_input,
            }
        )
