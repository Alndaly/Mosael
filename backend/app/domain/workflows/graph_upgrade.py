"""**图升级**:一张可能是旧形状的图,改成现在的形状。迁移、导入旧文件、恢复旧修订共用这一处。

形状变了的时候,库里的图由迁移一次改好 —— 可旧形状还有别的路回来:导入一份老版本导出的文件、把工作流
恢复到升级之前的某一版。此前这两条路原样落库,于是迁移修好的东西又回来了(循环的 output 又是一条外层数据
边、代码字段里的 `{{…}}` 又成了不起作用的字面量)。所以「旧 → 新」的改写写在领域层,三条路调同一个函数。

每一步都**只认旧形状**,新形状的图原样过:可以对任何一张图放心地调,调几次都一样。

- 被旧规范化**折掉**的控制边 → 按历史判据补回来(见 `drawn_control_edges_come_back`);
- 循环 / 子图的体内字段(output、condition)被旧规范化接成了外层数据边 → 改回体内引用
  (见 `inner_scope_fields_come_back`);
- 代码字段里的 `{{…}}`(老版本按文字插值)→ 挪进入参、代码改成读入参(见 `code_references_read_input`);
- 插件节点的数组入参存成「名字 → 值」对象 → 值的列表:这一步要知道哪一格是数组,在规范化里
  (normalization.canonicalize_list_fields,保存、导入、模板都走它);
- 开始节点的必填参数写成一串逗号分隔的名字 → 参数名的列表(见 `start_required_params_become_a_list`)。
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.workflows.code_references import REFERENCE, declares_input, references_become_input
from app.domain.workflows.graph_rules import BRANCHING_NODE_TYPES, NESTED_BODY_TYPES
from app.domain.workflows.node_types import NODE_TYPES
from app.domain.workflows.normalization import required_params_as_rows

#: 内嵌子图节点的哪几格属于体内作用域(和 graph_rules.NESTED_BODY_RAW_KEYS 同一条界线,body 本身除外)。
_INNER_FIELDS = {"loop_foreach": ("output",), "loop_while": ("output", "condition"), "subgraph": ("output",)}

#: 代码字段与它的语言。代码字段的执行方式(Python 沙箱 / 网页里的 JS)由节点决定,改写要按语言认字符串。
CODE_FIELDS = {"code": ("code", "python"), "browser_evaluate": ("expression", "js")}


def upgrade_graph(graph: Any) -> Any:
    """一张图(连同循环体 / 子图体)改成现在的形状。不是图的原样交回;不改传进来的那份。"""
    return start_required_params_become_a_list(
        code_references_read_input(drawn_control_edges_come_back(inner_scope_fields_come_back(graph)))
    )


def start_required_params_become_a_list(graph: Any) -> Any:
    """开始节点的 `required_params` 是一串逗号分隔的名字(旧形状)→ 参数名的列表。

    旧面板上它是一格独立的文本框:同一个名字写两遍,半角全角逗号、多余的空格都有。拆开之后按规范形状收拾
    (normalization.required_params_as_rows):去重、按参数的顺序,点名了却没有那一行的补一行(默认空着)——
    它照旧是必填,运行前照旧拦。已经是列表的原样过。开始节点只在顶层。
    """
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return graph
    nodes = []
    for node in graph["nodes"]:
        config = node.get("config") if isinstance(node, dict) else None
        if isinstance(config, dict) and node.get("type") == "start" and isinstance(config.get("required_params"), str):
            names = config["required_params"].replace("，", ",").split(",")
            node = {**node, "config": required_params_as_rows({**config, "required_params": names})}
        nodes.append(node)
    return {**graph, "nodes": nodes}


def drawn_control_edges_come_back(graph: Any) -> Any:
    """旧数据里**被规范化折掉**的控制边,按当年那条判据补回来。新形状的图原样交回。

    ## 为什么要有这一步

    2026-10-02 到 2026-10-16 之间,规范化(`normalization.canonicalize_data_bindings`)把作者画的、
    **同一对节点间已经/即将有一条数据边**的无 handle 控制边当多余的折掉(判据见下)。维护者
    2026-10-16 拍板不折了(`docs/adr/0063-画出来的控制边一律保留.md`),可**当年存的那些图里那些边
    已经不在了** —— 规范化只加数据边、从不凭空补控制边,所以老图不会自己长回来。补回来这一步
    就在这里:迁移(`db/migrations._migrate_restore_drawn_control_edges`)、导入旧文件、恢复旧修订
    三条路共用(和这个模块里别的「旧 → 新」改写同一条规矩)。

    ## 当年的判据(e35979a10^ 的 normalization.py,只读复刻)

        routes(edge)        来源节点声明了 branches(条件的真 / 假出口)就是「带路由语义」
        ordering_only(e)    kind 是 control、没写 source_handle、来源不 branches、
                            且 (来源, 目标) 在 upgraded_pairs 里(这一趟刚从精确引用升级出数据边)
        routing(e)          kind 是 control 且(写了 source_handle 或来源 branches)
        foldable_into(T)    T 另有 routing 边 → 折;否则「T 的普通控制边来源集合」== 「T 的数据边来源集合」→ 折
        redundant(e)        ordering_only(e) and foldable_into(e.target)
        edges = [e for e in edges if not redundant(e)]      ← 被删掉的就是这些

    **这套判据只用来认旧数据,不要再放回规范化路径**(维护者的决定:画出来的边一律保留)。

    ## 什么样的「缺一条控制边」证得出来

    落库的图是折过之后的:作者画的那条边连 id 都没留下,只能从「同一对节点间有一条数据边」认回去。
    于是要问的是:见到「目标 T 没有普通控制入边、却有来自 S 的数据入边」,当年那条 S→T 控制边是不是
    被折了?两种作者意图落库是**同一个样子**:

    · 画了 S→T,规范化折了(折前 T 的普通控制边来源 == T 的数据边来源,foldable 成立);
    · 根本没画 S→T,只是把 `{{S.输出}}` 写进了 T 的配置(规范化升成数据边,没有控制边可折)。
      —— 官方模板里这样的对子就有 60 处。

    所以「缺一条边」本身**不是证据**。能证的只有一种形状:**T 一条控制入边都没有**。这时若当年折过
    (foldable 成立),则「T 的普通控制边来源集合 == T 的数据边来源集合」要求 T 的数据边来源**每一个**
    都画过一条控制边 —— 于是这条形状下「T 的每一条数据边来源都补一条控制边」是**被逼出来的**,不是猜。
    而 T 只要还有一条普通控制入边、或有一条路由控制入边,当年折没折就分不出来:那里一条都不补
    (官方模板上 68 条被折的边,这样补回 58 条,剩下的 10 条全落在「T 另有条件的真 / 假出口」这一形状里;
    15 张模板补完沿控制边从开始都走得到交付)。

    补回来的边**判据自己就不再成立**(它成了 T 的普通控制入边),所以跑第二遍什么都不做 —— 幂等。

    ## 不动的部分

    节点的 inputs / 配置、别的边、边序、坐标,一律不动。补的边 id 沿用这个模块里 `inner_scope_fields_come_back`
    的习惯(`c-{来源}-{目标}`,撞了加序号),来源节点声明了 branches 的数据边不补(那种来源的控制边当年
    本来就不会折)。**插件节点的 branches 元数据看不到**(那要读这台机器上装了什么,迁移不能依赖)——
    按「不分支」处理,和「插件没装时」的规范化判法一致。
    """
    if not isinstance(graph, dict):
        return graph
    nodes = [dict(node) if isinstance(node, dict) else node for node in graph.get("nodes") or []]
    by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    edges: list[Any] = [dict(edge) if isinstance(edge, dict) else edge for edge in graph.get("edges") or []]
    restored = _control_edges_the_old_normalizer_folded(edges, by_id)
    used = {str(edge.get("id")) for edge in edges if isinstance(edge, dict)}
    for source, target_id in restored:
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
                config[key] = drawn_control_edges_come_back(value)
        if config != (node.get("config") or {}):
            node["config"] = config
    return {**graph, "nodes": nodes, "edges": edges}


def _control_edges_the_old_normalizer_folded(edges: list[Any], by_id: dict[str, Any]) -> list[tuple[str, str]]:
    """(来源, 目标) 列表:这一层里「当年折得掉、而且折了」判据成立时被删掉的那些控制边。判据见上。"""

    def branches(node_id: str) -> bool:
        return str((by_id.get(node_id) or {}).get("type", "")) in BRANCHING_NODE_TYPES

    data_sources: dict[str, set[str]] = {}
    candidates: dict[str, set[str]] = {}
    plain: dict[str, set[str]] = {}
    routed: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if not source or not target:
            continue
        if str(edge.get("kind")) == "data":
            data_sources.setdefault(target, set()).add(source)
            #: 来源会分支的数据边不在这里:那种来源的控制边当年算「带路由语义」,一条都没折过。
            if not branches(source):
                candidates.setdefault(target, set()).add(source)
            continue
        if str(edge.get("kind", "control")) != "control":
            continue
        #: 写了 handle 或来源会分支 = 带路由语义(当年的 routing):它们当年不会折,现在也不补。
        if edge.get("source_handle") or branches(source):
            routed.add(target)
        else:
            plain.setdefault(target, set()).add(source)

    restored: list[tuple[str, str]] = []
    for target, sources in sorted(candidates.items()):
        missing = sources - plain.get(target, set())
        if not missing:
            continue
        if target in routed:
            #: 目标另有条件的真 / 假出口:当年折没折分不出来(折了也不改谁该跑),不补。
            continue
        if plain.get(target, set()) & sources:
            #: 同格上还留着一条「同一对节点间有数据边」的普通控制边 —— 当年这条都折不掉,说明这一格根本没折。
            continue
        if plain.get(target, set()) | sources != data_sources.get(target, set()):
            #: foldable_into 当年要求的两组来源相等,这里对不上:这一格不是「折过」的样子。
            continue
        restored.extend((source, target) for source in sorted(missing))
    return restored


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


def code_references_read_input(
    graph: Any, *, scope: frozenset[str] = frozenset(), skipped: list[str] | None = None
) -> Any:
    """代码字段里**指得到东西**的 `{{…}}` 挪进节点的入参(`input`),代码改成读入参(改写规则见 code_references)。

    老版本按文字把 `{{…}}` 插进代码;现在代码原样执行,上游的值作为数据从入参进。只改根指得到东西的引用 ——
    这一层的节点,体内还有容器声明的作用域名(`loop`、`input`)。现在的代码里写一个 `{{name}}`(比如在拼一段
    Mustache 模板)是字面量,不是引用,不该被改成去读一个不存在的节点。

    入参的键由引用路径起名(`llm-1.text` → `llm_1_text`),和已有的键撞了就加序号;同一个引用只占一个键;
    入参里已经有这个引用的,直接用那个键。`scope` 是外层给体内带进来的作用域名。

    「执行脚本」**自己声明了 input** 的(见 code_references.declares_input)不改:改成 `input.k` 读到的是脚本
    自己的变量,静默取空。这种节点的 id 记进 `skipped`(给了的话),由调用方说出来(迁移记进修订说明)。
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
            config["body"] = code_references_read_input(config["body"], scope=inner, skipped=skipped)
        field = CODE_FIELDS.get(node_type)
        if field is not None and isinstance(config.get(field[0]), str):
            if field[1] == "js" and declares_input(config[field[0]]):
                if skipped is not None and REFERENCE.search(config[field[0]]):
                    skipped.append(str(node.get("id")))
            else:
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
