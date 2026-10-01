"""**图升级**:一张可能是旧形状的图,改成现在的形状。迁移、导入旧文件、恢复旧修订共用这一处。

形状变了的时候,库里的图由迁移一次改好 —— 可旧形状还有别的路回来:导入一份老版本导出的文件、把工作流
恢复到升级之前的某一版。此前这两条路原样落库,于是迁移修好的东西又回来了(循环的 output 又是一条外层数据
边、代码字段里的 `{{…}}` 又成了不起作用的字面量)。所以「旧 → 新」的改写写在领域层,三条路调同一个函数。

每一步都**只认旧形状**,新形状的图原样过:可以对任何一张图放心地调,调几次都一样。

- 循环 / 子图的体内字段(output、condition)被旧规范化接成了外层数据边 → 改回体内引用
  (见 `inner_scope_fields_come_back`);
- 代码字段里的 `{{…}}`(老版本按文字插值)→ 挪进入参、代码改成读入参(见 `code_references_read_input`);
- 插件节点的数组入参存成「名字 → 值」对象 → 值的列表:这一步要知道哪一格是数组,在规范化里
  (normalization.canonicalize_list_fields,保存、导入、模板都走它)。
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.workflows.code_references import REFERENCE, references_become_input
from app.domain.workflows.graph_rules import NESTED_BODY_TYPES
from app.domain.workflows.node_types import NODE_TYPES

#: 内嵌子图节点的哪几格属于体内作用域(和 graph_rules.NESTED_BODY_RAW_KEYS 同一条界线,body 本身除外)。
_INNER_FIELDS = {"loop_foreach": ("output",), "loop_while": ("output", "condition"), "subgraph": ("output",)}

#: 代码字段与它的语言。代码字段的执行方式(Python 沙箱 / 网页里的 JS)由节点决定,改写要按语言认字符串。
CODE_FIELDS = {"code": ("code", "python"), "browser_evaluate": ("expression", "js")}


def upgrade_graph(graph: Any) -> Any:
    """一张图(连同循环体 / 子图体)改成现在的形状。不是图的原样交回;不改传进来的那份。"""
    return code_references_read_input(inner_scope_fields_come_back(graph))


def inner_scope_fields_come_back(graph: Any) -> Any:
    """被旧规范化错接成外层数据边的循环 / 子图 `output`、条件循环 `condition`,改回体内引用。

    旧规范化只跳过 object / graph 类型的字段,没排除内嵌子图节点的 output / condition —— 节点 id 只在当前这一层
    唯一,体内引用 `{{llm-1.text}}` 被升级成一条来自**外层** llm-1 的数据边、那一格清空。

    认法:目标是循环 / 子图、`target_input` 是它那一格体内字段的数据边(外层一个值当每一轮的输出模板没有意义,
    不会是有意接的),一律删掉;那一格还空着就恢复成 `{{来源.输出}}`,已经重填过的不动;`inputs` 端口列表里
    那一项一并摘掉。删边后这一对节点之间什么边都不剩时补一条控制边 —— 规范化当初把它们之间无 handle 的控制边
    当多余的折掉了,补回的正是那一条。
    """
    if not isinstance(graph, dict):
        return graph
    nodes = [dict(node) if isinstance(node, dict) else node for node in graph.get("nodes") or []]
    by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    edges: list[Any] = []
    restored: list[tuple[str, str]] = []
    for edge in graph.get("edges") or []:
        target = by_id.get(str(edge.get("target"))) if isinstance(edge, dict) else None
        key = str(edge.get("target_input") or "") if isinstance(edge, dict) else ""
        if target is None or edge.get("kind") != "data" or key not in _INNER_FIELDS.get(str(target.get("type")), ()):
            edges.append(edge)
            continue
        config = dict(target.get("config") or {})
        if config.get(key) in (None, ""):
            config[key] = f"{{{{{edge.get('source')}.{edge.get('source_output')}}}}}"
        target["config"] = config
        if isinstance(target.get("inputs"), list):
            target["inputs"] = [one for one in target["inputs"] if one != key]
        restored.append((str(edge.get("source")), str(edge.get("target"))))
    used = {str(edge.get("id")) for edge in edges if isinstance(edge, dict)}
    for source, target_id in restored:
        if any(
            isinstance(edge, dict) and str(edge.get("source")) == source and str(edge.get("target")) == target_id
            for edge in edges
        ):
            continue
        edge_id, suffix = f"c-{source}-{target_id}", 2
        while edge_id in used:
            edge_id, suffix = f"c-{source}-{target_id}-{suffix}", suffix + 1
        used.add(edge_id)
        edges.append({"id": edge_id, "source": source, "target": target_id})
    for node in nodes:
        if not isinstance(node, dict):
            continue
        config = dict(node.get("config") or {})
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                config[key] = inner_scope_fields_come_back(value)
        if config != (node.get("config") or {}):
            node["config"] = config
    return {**graph, "nodes": nodes, "edges": edges}


def code_references_read_input(graph: Any, *, scope: frozenset[str] = frozenset()) -> Any:
    """代码字段里**指得到东西**的 `{{…}}` 挪进节点的入参(`input`),代码改成读入参(改写规则见 code_references)。

    老版本按文字把 `{{…}}` 插进代码;现在代码原样执行,上游的值作为数据从入参进。只改根指得到东西的引用 ——
    这一层的节点,体内还有容器声明的作用域名(`loop`、`input`)。现在的代码里写一个 `{{name}}`(比如在拼一段
    Mustache 模板)是字面量,不是引用,不该被改成去读一个不存在的节点。

    入参的键由引用路径起名(`llm-1.text` → `llm_1_text`),和已有的键撞了就加序号;同一个引用只占一个键;
    入参里已经有这个引用的,直接用那个键。`scope` 是外层给体内带进来的作用域名。
    """
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return graph
    roots = scope | {str(node.get("id")) for node in graph["nodes"] if isinstance(node, dict)}
    nodes = []
    for node in graph["nodes"]:
        if not isinstance(node, dict):
            nodes.append(node)
            continue
        config = dict(node.get("config") or {})
        node_type = str(node.get("type") or "")
        if node_type in NESTED_BODY_TYPES and isinstance(config.get("body"), dict):
            inner = frozenset(NODE_TYPES[node_type].get("body_scope") or {})
            config["body"] = code_references_read_input(config["body"], scope=inner)
        field = CODE_FIELDS.get(node_type)
        if field is not None and isinstance(config.get(field[0]), str):
            config = _read_input(config, *field, roots)
        nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
    return {**graph, "nodes": nodes}


def _read_input(config: dict[str, Any], field: str, language: str, roots: set[str] | frozenset[str]) -> dict[str, Any]:
    code = config[field]
    if not any(match.group(1).split(".")[0] in roots for match in REFERENCE.finditer(code)):
        return config
    given = config.get("input") if isinstance(config.get("input"), dict) else {}
    inputs = dict(given)

    def key_of(path: str) -> str:
        reference = "{{" + path + "}}"
        for key, value in inputs.items():
            if value == reference:
                return key
        base = re.sub(r"\W", "_", path)
        base = base if base and not base[0].isdigit() else f"v_{base}"
        key, n = base, 2
        while key in inputs:
            key, n = f"{base}_{n}", n + 1
        inputs[key] = reference
        return key

    #: 指不到东西的引用原样留在代码里(它是字面量):包一层,改写器只看见指得到的那些。
    marker = "\0"

    def hide(match: re.Match[str]) -> str:
        return match.group(0) if match.group(1).split(".")[0] in roots else match.group(0).replace("{{", marker)

    rewritten = references_become_input(REFERENCE.sub(hide, code), language, key_of).replace(marker, "{{")
    return {**config, field: rewritten, "input": inputs}
