"""工作流图的规则:校验、拓扑序、变量插值、外部节点识别。只读 NODE_TYPES,不碰数据库以外的状态。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.domain.workflows.field_activation import config_field_active
from app.domain.workflows.node_types import (
    NODE_TYPES,
)

VARIABLE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def code_fields(node_type: str, types: dict[str, dict[str, Any]] | None = None) -> set[str]:
    """这种节点的哪几格是代码(`"type": "code"`)。

    代码字段**不插值**(见 binding.interpolate_node_config):里面写的 `{{…}}` 原样留在代码里,不是引用 ——
    不算依赖、不查作用域,也不能接数据边(上游的值整段变成代码,和把 {{}} 拼进去是同一个注入)。上游的值走
    节点的入参(`input`)。
    """
    specs = ((types or NODE_TYPES).get(node_type) or {}).get("config") or {}
    return {key for key, spec in specs.items() if isinstance(spec, dict) and spec.get("type") == "code"}


def code_field_problems(graph: Any, types: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """代码字段里写了 `{{…}}`、或者接了上游的数据边 —— 两样都是想把上游的值拼进代码(连同循环体 / 子图体里的)。

    代码字段不插值(见 code_fields):`{{…}}` 原样留在代码里,不会被换成上游的值 —— 写的人以为接上了,跑起来
    读到的是一串字面量;接数据边则是上游的值整段变成代码。上游的值走节点的入参(`input`)。

    保存不拦人手写的(`{{…}}` 在现在的代码里可以是字面量,比如在拼一段 Mustache 模板);**智能体**写图时
    拦 —— 它照着「字符串都能写 {{node.output}}」的习惯写进代码字段,用户批准之后才发现没接上。
    """
    if not isinstance(graph, dict):
        return []
    known = types or NODE_TYPES
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    bound = {
        (str(edge.get("target", "")), str(edge.get("target_input", "")))
        for edge in edges
        if isinstance(edge, dict) and str(edge.get("kind", "")) == "data" and edge.get("target_input")
    }
    problems: list[str] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id, node_type = str(node.get("id", "")), str(node.get("type", ""))
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        for key in sorted(code_fields(node_type, known)):
            if (node_id, key) in bound:
                problems.append(tr("wfErr_codeFieldBound", node=node_id, field=key))
            elif isinstance(config.get(key), str) and VARIABLE_RE.search(config[key]):
                problems.append(tr("wfErr_codeFieldReference", node=node_id, field=key))
        if node_type in NESTED_BODY_TYPES:
            problems.extend(code_field_problems(config.get("body"), types))
    return problems


def _referencing_config(node: dict[str, Any]) -> dict[str, Any]:
    """这个节点在**这一层**会被插值的那些配置:去掉内嵌子图的 body/output/condition(内层作用域)和代码字段。"""
    node_type = str(node.get("type") or "")
    skipped = set(code_fields(node_type))
    if node_type in NESTED_BODY_TYPES:
        skipped |= set(NESTED_BODY_RAW_KEYS)
    return {key: value for key, value in (node.get("config") or {}).items() if key not in skipped}


def _plugin_types(db: Session) -> dict[str, dict[str, Any]]:
    """当前可用的插件节点。延迟导入:plugins 域会反过来用到工作流的东西(插件工具执行器),
    顶层互相 import 就成了环。"""
    from app.domain.plugins.nodes import plugin_node_types

    return plugin_node_types(db)


#: 整格只有一条引用(和前端 analyze 的同一个写法):one_of 的「引用在前、兜底在后」只认这种。
PURE_REFERENCE_RE = re.compile(r"^\s*\{\{\s*[\w.-]+\s*\}\}\s*$")


def one_of_errors(
    node_id: str, config: dict[str, Any], specs: dict[str, Any], data_bound: set[tuple[str, str]]
) -> list[str]:
    """声明了 `one_of` 的每一组字段恰好填一个(见 NODE_TYPES 前的说明)。「填了」按 blank 判,和必填同一个判据。

    **引用在前、兜底在后**也行:按声明的顺序,最后一个填了的之前,填了的都是整格一条引用或接了数据边 ——
    运行时按顺序取第一个非空的,上游给空就落到后面那格。此前这种写法被判成「只能填一个」,而浏览器节点的
    迁移照这条规矩删掉了用户留的兜底。组里的字段写了 `one_of_strict` 的(执行器两样都给就报错)不算。
    """
    groups: dict[str, list[str]] = {}
    for key, spec in specs.items():
        if isinstance(spec, dict) and spec.get("one_of"):
            groups.setdefault(str(spec["one_of"]), []).append(key)
    errors = []
    for keys in groups.values():
        bound = {key for key in keys if (node_id, key) in data_bound}
        filled = [key for key in keys if not blank(config.get(key)) or key in bound]
        names = " / ".join(keys)
        strict = any(specs[key].get("one_of_strict") for key in keys)
        fallback = not strict and all(
            key in bound or (isinstance(config.get(key), str) and PURE_REFERENCE_RE.match(config[key]))
            for key in filled[:-1]
        )
        if len(filled) > 1 and not fallback:
            errors.append(f"节点 {node_id} 的 {names} 只能填一个")
        elif not filled:
            errors.append(f"节点 {node_id} 的 {names} 要填一个")
    return errors


def _start_param_errors(node_id: str, config: dict[str, Any]) -> list[str]:
    """开始节点勾了「必填」的参数(`required_params`,参数名的列表)一个都不能空。

    参数的值常常是模板建好之后才由用户填的(商品名、卖点、主题),而它们被别的节点用 `{{start.x}}` 引用 ——
    引用本身在必填检查里算"填了",所以此前空着也能启动,要等用到它的那一步才失败,或者更糟:模型对着空白
    照样写完、后面的付费生成照样扣费。形状不对的由 _required_params_shape_errors 报。
    """
    params = config.get("params") if isinstance(config.get("params"), dict) else {}
    names = config.get("required_params") if isinstance(config.get("required_params"), list) else []
    return [f"节点 {node_id} 缺少必填配置 params.{name}" for name in names if isinstance(name, str) and blank(params.get(name))]


def _required_params_shape_errors(node_id: str, config: dict[str, Any]) -> list[str]:
    """`required_params` 是参数名的列表。还写成一串逗号分隔的字的(旧形状,智能体照旧习惯写的)当场说清 ——
    不在这里猜着拆:旧形状由迁移和图升级改(graph_upgrade.start_required_params_become_a_list)。"""
    value = config.get("required_params")
    if value is None or (isinstance(value, list) and all(isinstance(name, str) for name in value)):
        return []
    return [tr("wfErr_requiredParamsShape", node=node_id)]


def blank(value: Any) -> bool:
    """一格**算不算空着**。必填、只能填一个(one_of)、运行参数盖不盖默认值,都按这一个判。

    和画布就绪检查(analyze.ts 的 isEmpty)同一个判据:0 和 false 是值,None、空串、空白、空列表 / 空对象不是。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, (list, dict)) and not value


def run_params(defaults: dict[str, Any] | None, params: dict[str, Any] | None) -> dict[str, Any]:
    """开始节点这一次的参数:声明的默认值,叠上这一次传进来的值。**传了个空的不算传了** —— 默认值照旧。

    表单、定时任务、子工作流的入参常常把没填的格子交成空串;此前它照样盖掉开始节点里写好的默认值,
    必填检查(按 blank 判)接着就说缺参数 —— 用户明明在开始节点里填过。没声明默认值的参数传空的,照旧
    留着那个空值(引用它的地方解析得到)。运行前校验(with_run_params)和执行(engine 的 start 节点)
    都经这里,不会一边判有、一边跑空。
    """
    merged = dict(defaults or {})
    for key, value in (params or {}).items():
        if blank(value) and key in merged:
            continue
        merged[key] = value
    return merged


def with_run_params(graph: dict[str, Any], params: dict[str, Any] | None) -> dict[str, Any]:
    """这张图**这一次运行**看到的样子:开始节点的参数叠上运行时传进来的值(和执行时 start 节点的合并同一份规矩,
    见 run_params)。

    运行前校验按它判必填参数 —— 默认值空着、但这次调用(定时任务、子工作流、接口)带了值的,不该被拦。
    """
    if not params:
        return graph
    nodes = []
    for node in graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("type") == "start":
            config = dict(node.get("config") or {})
            config["params"] = run_params(config.get("params"), params)
            node = {**node, "config": config}
        nodes.append(node)
    return {**graph, "nodes": nodes}


def validate_graph(
    graph: dict[str, Any],
    *,
    require_start: bool = True,
    require_config: bool = True,
    allow_missing_start: bool = False,
    extra_types: dict[str, dict[str, Any]] | None = None,
    explain_plugin_node: Callable[[str], str | None] | None = None,
) -> list[str]:
    """结构校验:返回错误列表(空表 = 合法)。

    explain_plugin_node:图里的插件节点不在 extra_types 里时,**为什么**(没装、没接连接、连接停用、工具没勾选……)。
    和 extra_types 一样由知道「谁在跑」的调用方给(见 engine.start_workflow_job);不给就只说是哪个插件的节点用不了。

    extra_types 是**动态**的节点类型(目前只有插件节点,见 domain/plugins/nodes.py):形状与
    NODE_TYPES 的条目一致,合并进来后校验、必填检查一视同仁。之所以从参数进来而不是在这里
    直接查库:这个函数是纯的,而"装了哪些插件"是调用方那一侧的事实 —— 拿不到 db 的调用方
    (比如子图体校验)照样能用它,只是那次校验里没有插件节点。

    require_config=False 用于**保存**:必填字段缺失属于「还没配完」,不该拦住存盘 —— 否则配合
    实时保存,新加一个带必填项的节点就永远存不下来。缺必填由「就绪检查」提示、由运行时拦截。

    allow_missing_start=True 同样用于**保存**:用户可以把画布清空或删除开始节点做草稿;
    运行时仍然 require_start=True 且 allow_missing_start=False,没有开始节点就不能运行。

    require_start=False 用于循环体子图:子图没有 start 节点(执行时由循环上下文喂入
    {{loop.item}}),无入边的节点即为入口;若子图里出现 start 则报错。
    """
    errors: list[str] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["graph 必须包含 nodes 与 edges 两个数组"]
    # Only the CONTAINERS were type-checked. Their elements were assumed to be dicts, so
    # {"nodes": ["oops"]} reached .get() and raised AttributeError straight past the
    # WorkflowDomainError handler — a 500 for what is plainly a bad request. This has to come
    # before the first .get() below, not after.
    if any(not isinstance(node, dict) for node in nodes) or any(not isinstance(e, dict) for e in edges):
        return ["节点与连线必须是对象"]

    # 标记(位置书签)不是节点:它不执行、不连线,只是"跳到这儿"。所以它在 graph 里自成一份
    # 列表,校验也自成一条 —— 规则见 domain/markers,画板那边用的是同一份。
    from app.domain.markers import marker_errors

    errors.extend(marker_errors(graph.get("markers")))

    # 数据边(kind="data")把上游输出绑到目标输入 → 该输入即便字面量为空也算已满足。
    data_bound: set[tuple[str, str]] = {
        (str(edge.get("target", "")), str(edge.get("target_input", "")))
        for edge in edges
        if str(edge.get("kind", "")) == "data" and edge.get("target_input")
    }

    known_types = {**NODE_TYPES, **(extra_types or {})}

    def _unknown_type_error(node_type: str, node_id: str) -> str:
        # 插件节点在别人机器上会缺:说清楚是"缺哪个插件"、为什么用不了,而不是一句让人无从下手的"未知类型"。
        from app.domain.plugins.nodes import parse_node_type

        parsed = parse_node_type(node_type)
        if parsed:
            why = explain_plugin_node(node_type) if explain_plugin_node is not None else None
            return tr("wfErr_pluginNodeUnusable", node=node_id, reason=why or tr("wfErr_pluginNodeUnknownReason",
                                                                                  plugin=parsed[0], tool=parsed[1]))
        return f"未知节点类型: {node_type} ({node_id})"

    seen_ids: set[str] = set()
    start_count = 0
    for node in nodes:
        node_id = str(node.get("id", ""))
        node_type = str(node.get("type", ""))
        if not node_id:
            errors.append("存在缺少 id 的节点")
            continue
        if node_id in seen_ids:
            errors.append(f"节点 id 重复: {node_id}")
        seen_ids.add(node_id)
        if node_type not in known_types:
            errors.append(_unknown_type_error(node_type, node_id))
            continue
        if node_type == "start":
            start_count += 1
            errors.extend(_required_params_shape_errors(node_id, node.get("config") or {}))
        if require_config:
            node_config = node.get("config") or {}
            node_specs = known_types[node_type]["config"]
            for key, spec in node_specs.items():
                if isinstance(spec, dict) and spec.get("required") and config_field_active(spec, node_config, node_specs):
                    value = node_config.get(key)
                    #: 「空着」和画布的就绪检查同一个判据(blank):空白、空列表、空对象也是没填。
                    if blank(value) and (node_id, key) not in data_bound:
                        errors.append(f"节点 {node_id} 缺少必填配置 {key}")
            errors.extend(one_of_errors(node_id, node_config, node_specs, data_bound))
            #: 代码字段不能接上游:上游的值整段变成代码,和把 {{}} 拼进去是同一个注入(见 code_fields)。
            errors.extend(
                tr("wfErr_codeFieldBound", node=node_id, field=key)
                for key in sorted(code_fields(node_type, known_types))
                if (node_id, key) in data_bound
            )
            if node_type == "start":
                errors.extend(_start_param_errors(node_id, node_config))
            #: **运行前的校验要下到内嵌子图里,而且是整份校验。** 体是这张图的一段,它的每一种错
            #: (缺必填、引用越出作用域、空体、体里有开始节点、环、未知类型)在这里不报,就只能等
            #: 循环真跑到时才由执行器报 —— 那时工作流已经占了一个任务位、把循环之前的步骤全跑完
            #: (在「从主题到完整视频」里那是好几次付费的 AI 调用),而同一处遗漏写在顶层是当场
            #: 422、免费、且指得准。
            #:
            #: 此前这里只下探「缺必填」一项,其余的留给执行器在运行时再校验一遍 —— 而那一遍拿不到
            #: `extra_types`,于是**循环体里的插件节点一律被判「未安装或未启用」**。现在体只在这里
            #: 校验一次,带着和外层同一份节点类型。
            if node_type in NESTED_BODY_TYPES:
                where = f"节点 {node_id} 的{_body_label(node_type)}里:"
                errors.extend(
                    where + one
                    for one in validate_body_graph(
                        node_config.get("body"), node_type, extra_types=extra_types, container=node_config,
                        explain_plugin_node=explain_plugin_node,
                    )
                )
    if require_start:
        if start_count > 1 or (start_count == 0 and not allow_missing_start):
            errors.append(f"工作流必须恰好包含 1 个开始节点(当前 {start_count} 个)")
        #: 顶层的 `{{节点.字段}}` 要指向本图里的节点、`{{开始.参数}}` 要是开始节点有的参数。只在**运行前**
        #: (require_config)查:保存时删掉一个节点、引用它的那几格还没改,不该连存都存不下(画布会标出
        #: 失效引用)。体内的引用另有作用域规则(见 validate_body_graph)。
        if require_config:
            errors.extend(_unresolved_reference_errors(nodes, edges))
    elif start_count > 0:
        errors.append("循环体子图不能包含开始节点")
    #: **会跑的节点引用了一定不会跑的节点**(没接进流程):那个引用跑起来只会是空串,工作流照样报成功 ——
    #: 「从主题到完整视频」的「可用的 3D 道具」从模板 v8 到 v11 一次都没跑过,画布上只挂着一个黄色提醒。
    #: 只在**运行前**(require_config)拦:保存不拦,旧图照样存得下、打得开,用户才连得上它、或者按新版重建。
    #: 顶层没有开始节点时什么都不会跑,上面已经说了这一件,不再逐个报。循环体 / 子图按它们自己的入口规则
    #: (无入边的根也是入口,见 never_run_nodes)。
    if require_config and (start_count > 0 or not require_start):
        separator = tr("punct_listSep")
        errors.extend(
            tr("wfErr_referencesNeverRunNode", nodes=separator.join(one["referenced_by"]),
               refs=separator.join(one["refs"]), source=one["source"])
            for one in never_run_references({"nodes": nodes, "edges": edges}, entry_is_root=not require_start)
        )

    node_types = {str(node.get("id", "")): str(node.get("type", "")) for node in nodes}
    adjacency: dict[str, list[str]] = {}
    indegree: dict[str, int] = {node_id: 0 for node_id in seen_ids}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in seen_ids or target not in seen_ids:
            errors.append(f"连线引用了不存在的节点: {source} → {target}")
            continue
        handle = edge.get("source_handle")
        branches = known_types.get(node_types.get(source, ""), {}).get("branches")
        if branches and handle not in (None, *branches):
            errors.append(f"条件节点的分支端点必须是 {'/'.join(branches)}: {source}")
        adjacency.setdefault(source, []).append(target)
        indegree[target] = indegree.get(target, 0) + 1
    #: 引用即依赖(见 reference_dependencies):一个节点引用了它自己的下游,就是一个环 ——
    #: 此前它照样能跑,只是取到空值,而这是最难发现的那种失败。
    for target, sources in reference_dependencies({"nodes": nodes}).items():
        for source in sources:
            adjacency.setdefault(source, []).append(target)
            indegree[target] = indegree.get(target, 0) + 1

    # Kahn 拓扑排序检环
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    degrees = dict(indegree)
    while queue:
        current = queue.pop()
        visited += 1
        for nxt in adjacency.get(current, []):
            degrees[nxt] -= 1
            if degrees[nxt] == 0:
                queue.append(nxt)
    if seen_ids and visited != len(seen_ids):
        errors.append("工作流包含环路(连线或 {{节点.…}} 引用绕回了自己),必须是有向无环图")
    return errors


def _outer_references(node: dict[str, Any]) -> list[list[str]]:
    """一个节点的配置里**在这一层解析**的引用(按点号拆开)。容器节点的体内字段不算 —— 它们属于体内作用域;
    代码字段也不算 —— 它不插值(见 code_fields)。"""
    config = _referencing_config(node)
    return [match.group(1).strip().split(".") for match in VARIABLE_RE.finditer(json.dumps(config, ensure_ascii=False))]


def _unresolved_reference_errors(nodes: list[Any], edges: list[Any]) -> list[str]:
    """顶层引用解析得到:根是本图里的节点;引到开始节点的,那个参数开始节点有。

    此前后端不查:画布会标出失效引用,可定时任务、智能体、call_workflow 触发的运行不经过画布 ——
    一个拼错的 `{{scirpt.text}}`、调用方少传的 `{{start.topic}}` 运行时静默插值成空串,下游拿着
    空提示词去付费生成。

    开始节点"有"哪些参数是**这一次运行**说了算的:运行前校验拿的是 with_run_params 叠过本次参数的图,
    所以这里只看开始节点 config 里的 params —— 声明了的、这次传进来的都在里面。从开始节点拉出的
    数据边(`source_output` 就是参数名)同一条规矩。
    """
    ids = {str(node.get("id", "")) for node in nodes if isinstance(node, dict)}
    starts = {
        str(node.get("id", "")): set((node.get("config") or {}).get("params") or {})
        for node in nodes
        if isinstance(node, dict) and node.get("type") == "start"
    }
    errors: list[str] = []
    missing: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        references = _outer_references(node)
        unknown = sorted({parts[0] for parts in references if parts[0] and parts[0] not in ids})
        if unknown:
            errors.append(f"节点 {node.get('id')} 引用了不存在的节点:{', '.join(unknown)}")
        missing |= {
            f"{parts[0]}.{parts[1]}"
            for parts in references
            if parts[0] in starts and len(parts) > 1 and parts[1] not in starts[parts[0]]
        }
    for edge in edges:
        source, output = str(edge.get("source", "")), str(edge.get("source_output", ""))
        if edge.get("kind") == "data" and source in starts and output and output not in starts[source]:
            missing.add(f"{source}.{output}")
    if missing:
        errors.append(f"开始节点没有这些参数:{', '.join(sorted(missing))};在开始节点里声明它们,或运行时传进来")
    return errors


#: 内嵌子图类节点(循环体 / subgraph):**由节点自己声明**体内看得见什么(`body_scope`)——
#: 作用域名 → 这个名字底下的字段。`*字段名` 表示「这个配置字段里的每个键」(和 start 的 `*params`
#: 输出同一种写法):子图的 `{{input.*}}` 是用户自己在 `inputs` 里起的名字,只有运行时那份配置知道。
#:
#: 这份声明是各方的单一真源:执行器给体播种的就是这些(run_body 逐名逐字段核对);校验据此判断
#: 体内的引用有没有越出作用域;画布的就绪检查和体内的引用选择器经 /api/workflows/node-types
#: 拿到同一格。选择器此前按「是不是子图」自己写了一份,条件循环体里也列出了拿不到的 `loop.item`。此前三方各写各的 ——
#: 校验对所有循环一律放行 `loop` 与 `input`,可条件循环(loop_while)根本不播 `input`,于是
#: 体内的 `{{input.x}}` 校验得过、运行时安静地变成空串;画布那一侧则对子图也放行 `loop`,
#: 后端却会拒绝 —— 同一张图,一边说能跑,一边说不能。
#:
#: body/output/condition 属于**内层**作用域(见 binding.interpolate_node_config 保留原文的理由),
#: 既是插值时机的依据,也是校验时不下钻的依据。binding.py 从这里取。
NESTED_BODY_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if spec.get("body_scope"))
NESTED_BODY_RAW_KEYS = ("body", "output", "condition")

#: 会分支的节点(条件):**控制边**从它出发时带路由语义 —— `source_handle` 说走哪一支,没写就是
#: 第一支(「真」)。数据边从它的输出口出发只说"值从哪来",不参与路由。
#:
#: 由节点声明(`branches`),引擎路由、保存校验、规范化折叠边都读这一格。此前引擎对来自条件节点
#: 的**每一条**边都做路由,于是把 `result` 输出接进一个节点,条件为假时那个节点整个被跳过;
#: 规范化则把"同一对节点间已有数据边"的无 handle 控制边当多余的折掉,连带折掉了它的路由语义。
BRANCHING_NODE_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if spec.get("branches"))


def _body_label(node_type: str) -> str:
    return "循环体" if "loop" in NODE_TYPES[node_type]["body_scope"] else "子图"


def validate_body_graph(
    body: Any,
    node_type: str,
    *,
    extra_types: dict[str, dict[str, Any]] | None = None,
    container: dict[str, Any] | None = None,
    explain_plugin_node: Callable[[str], str | None] | None = None,
) -> list[str]:
    """内嵌子图(循环体 / subgraph)校验:必须非空、无 start 节点、其余同 validate_graph;
    再查引用是否越出 `node_type` 声明的作用域(`body_scope`)。

    `container` 是容器节点自己的配置:它的 output / condition(见 NESTED_BODY_RAW_KEYS)也在体内
    作用域里解析,一并按同一份作用域查。此前只扫体里的节点,这两格前后端都不看 —— 条件循环的条件
    写错一个节点名,运行时插值成空串,循环安静地只跑一轮。

    `extra_types` 和外层那次校验是同一份 —— 体里的插件节点和顶层的一样认得出来。"""
    label = _body_label(node_type)
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return [f"{label}不能为空,至少要有一个节点"]
    errors = validate_graph(
        body, require_start=False, extra_types=extra_types, explain_plugin_node=explain_plugin_node
    )
    #: 「输出」节点声明的是**整条工作流**交给调用方的东西,只在顶层算数(见 engine.run_workflow)。
    #: 放在体里它照样跑、产出却没人收 —— 看起来声明了输出,被调用时拿到的还是没有。
    if any(isinstance(node, dict) and node.get("type") == "output" for node in nodes):
        errors.append(f"{label}里不能放「输出」节点:工作流的输出只能在最外层声明")
    errors.extend(_unresolvable_body_refs(nodes, node_type))
    if container:
        inner = {key: container[key] for key in NESTED_BODY_RAW_KEYS if key != "body" and key in container}
        errors.extend(_unresolvable_container_refs(inner, nodes, node_type))
    return errors


def _body_refs(texts: list[str], nodes: list[Any], node_type: str) -> tuple[set[str], set[str]]:
    """这几段文字里,体内作用域解析不了的引用:(不认识的根, 固定作用域里没有的字段)。

    体内看得见的只有节点类型声明的作用域名(`body_scope`)和体里自己的节点。字段是固定几个的
    作用域(`loop`),字段也要对得上;字段来自配置的(`*inputs`)只有运行时知道。
    """
    declared: dict[str, list[str]] = NODE_TYPES[node_type]["body_scope"]
    body_ids = {str(node.get("id", "")) for node in nodes if isinstance(node, dict)}
    known = set(declared) | body_ids
    fixed = {root: set(fields) for root, fields in declared.items() if not any(one.startswith("*") for one in fields)}
    unknown: set[str] = set()
    missing: set[str] = set()
    for text in texts:
        for match in VARIABLE_RE.finditer(text):
            parts = match.group(1).strip().split(".")
            root = parts[0]
            if root and root not in known:
                unknown.add(root)
            elif root in fixed and root not in body_ids and len(parts) > 1 and parts[1] not in fixed[root]:
                missing.add(f"{root}.{parts[1]}")
    return unknown, missing


def _missing_fields_error(missing: set[str], node_type: str) -> str:
    fixed = {
        root: fields for root, fields in NODE_TYPES[node_type]["body_scope"].items()
        if not any(one.startswith("*") for one in fields)
    }
    provided = "、".join(f"{root}.{field}" for root, fields in fixed.items() for field in sorted(fields))
    return f"{_body_label(node_type)}里没有 {', '.join(sorted(missing))};这里只提供 {provided}"


def _unresolvable_body_refs(nodes: list[Any], node_type: str) -> list[str]:
    """Reject a body template that references anything outside its own scope.

    A body context is seeded with the scope names its node type declares (`body_scope`) and the
    body's own nodes — nothing else. A body node referencing an outer node like {{start.prefix}}
    therefore interpolated to the empty string: no error, no warning, just silently missing text in
    whatever the body produced. That is the worst failure mode available, so name it at validation
    time instead.

    (Making the body actually see the outer scope is not a matter of passing more context: body,
    output and condition are deliberately left un-interpolated at the outer scope so that
    {{loop.item}} / {{input.x}} survive to be resolved when the body runs. Outer values reach a
    body through the node's `inputs`, which keeps the dependency visible on the canvas.)

    Nested bodies are NOT descended into here: a nested loop/subgraph node's own
    body/output/condition belong to *its* inner scope and validate_graph checks them against that
    scope. Its `inputs`/`items` (outer-facing) are still scanned, since those resolve in *this* scope.
    """
    texts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        texts.append(json.dumps(_referencing_config(node), ensure_ascii=False))
    unknown, missing = _body_refs(texts, nodes, node_type)
    errors: list[str] = []
    if missing:
        errors.append(_missing_fields_error(missing, node_type))
    if not unknown:
        return errors
    allowed = "、".join(NODE_TYPES[node_type]["body_scope"])
    if "loop" in NODE_TYPES[node_type]["body_scope"]:
        return [*errors, f"循环体引用了循环外的节点:{', '.join(sorted(unknown))};循环体只能引用 {allowed} 与体内节点"]
    return [*errors, f"子图引用了作用域外的节点:{', '.join(sorted(unknown))};子图只能引用 {allowed} 与体内节点"]


def _unresolvable_container_refs(inner: dict[str, Any], nodes: list[Any], node_type: str) -> list[str]:
    """容器节点自己的 output / condition 在体内作用域里解析 —— 和体里的节点同一份作用域。"""
    label = _body_label(node_type)
    errors: list[str] = []
    for key, value in inner.items():
        unknown, missing = _body_refs([json.dumps(value, ensure_ascii=False)], nodes, node_type)
        if missing:
            errors.append(_missing_fields_error(missing, node_type))
        if unknown:
            allowed = "、".join(NODE_TYPES[node_type]["body_scope"])
            errors.append(
                f"{key} 引用了{label}里没有的节点:{', '.join(sorted(unknown))};只能引用 {allowed} 与{label}里的节点"
            )
    return errors


#: 后果**落在这个应用之外**的节点:发出去的帖子、别人服务器上的改动、本机跑过的代码、
#: 用真实浏览器点下去的按钮。它们决定确认卡的权限档 —— `edit` 撤得回、`ai-cost` 最坏是花钱,
#: 这一档撤不回来。
#:
#: 浏览器节点整组算在内:一张图只要驱动浏览器,它做了什么就不再由这张图本身说了算。
#: `plugin_tool` 算在内:插件工具可以是写类的(manifest 里的 read_only 是自报的,不是判据)。
#: `call_workflow` 算在内是**保守**:它按 id 引用另一张图,扫描器跟不过去(跟过去要查库递归),
#: 「后果落在这个应用外面」的节点。**声明在节点自己身上**(`"external": True`)——
#: 加一个节点类型时作者必须在同一处说清它的后果落在哪,而不是记得去改另一头的一张表
#: (漏掉的那一个恰恰会是没人想过后果的那一个;由棘轮守着每个声明都有这一格)。
#:
#: 容器节点(loop/subgraph)本身是内部的 —— 危险的是它们的体,而体会被递归扫到。
EXTERNAL_NODE_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if spec.get("external"))
INTERNAL_NODE_TYPES = frozenset(name for name, spec in NODE_TYPES.items() if not spec.get("external"))

_MAX_GRAPH_SCAN_DEPTH = 16


#: 插件节点的类型前缀(`plugin.<插件id>.<工具名>`)。类型是**运行时**才知道的,所以它进不了
#: 上面那两张由声明派生的集合 —— 而它跑的是别人的代码,默认就该按"应用之外"算。
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX as _PLUGIN_NODE_PREFIX


def _is_external(node_type: str, types: frozenset[str]) -> bool:
    return node_type in types or (types is EXTERNAL_NODE_TYPES and node_type.startswith(_PLUGIN_NODE_PREFIX))


def _nodes_of_types(graph: Any, types: frozenset[str], *, _depth: int = 0) -> set[str]:
    """递归找出图里用到的、属于 `types` 的节点类型(含 loop/subgraph 的内嵌体)。

    **必须递归**:内嵌体是 config["body"] 里的一整张图,只查顶层的话,把节点框选「折叠为子图」
    就能整个绕过。深度上限只是防御畸形/自引用输入——真实嵌套受 MAX_NEST_DEPTH 约束,远小于它。

    两个扫描(特权 / 外部)共用这一段:递归本身是易错的部分,写两遍就会有一遍将来漏掉子图。
    """
    if _depth > _MAX_GRAPH_SCAN_DEPTH or not isinstance(graph, dict):
        return set()
    found: set[str] = set()
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type") or "")
        if _is_external(ntype, types):
            found.add(ntype)
        if ntype in NESTED_BODY_TYPES:
            found |= _nodes_of_types((node.get("config") or {}).get("body"), types, _depth=_depth + 1)
    return found


def external_nodes_in_graph(graph: Any) -> set[str]:
    """图里用到的**后果在应用之外**的节点 —— 决定确认卡的权限档(见 domain/agent/confirmations)。"""
    return _nodes_of_types(graph, EXTERNAL_NODE_TYPES)


def reference_dependencies(graph: dict[str, Any]) -> dict[str, set[str]]:
    """每个节点通过 `{{节点.…}}` **引用**了本图里的哪些节点。**引用即依赖**,只在这里算。

    此前"引用了谁"和"等谁跑完"是两件脱钩的事:引擎只按边调度,而规范化只会把「顶层字段、恰好
    两段路径」的引用变成数据边 —— `{{分镜.json.shots}}`(三段)或嵌在循环 `inputs` 对象里的
    `{{start.voice_id}}` 都不产生边。于是一个节点可能在它引用的节点跑完之前就开始,取到的是空值:
    官方模板靠作者手工补的控制边碰巧排好了顺序,用户自己搭的图则不一定。

    现在拓扑排序、环路校验、引擎调度都读这一份:被引用的节点落定(跑完或被跳过)之前,引用它的
    节点不开始;引用造成环路时保存/运行就报错。只决定**先后**,不决定"该不该跑"(那仍由控制边说了算)。

    内嵌子图(循环体 / subgraph)的 body/output/condition 属于**内层**作用域,不算在这一层的依赖里;
    它们的 `inputs` / `items` 在这一层解析,算。
    """
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    ids = {str(node.get("id", "")) for node in nodes}
    deps: dict[str, set[str]] = {}
    for node in nodes:
        node_id = str(node.get("id", ""))
        config = _referencing_config(node)
        roots = {match.group(1).strip().split(".")[0] for match in VARIABLE_RE.finditer(json.dumps(config, ensure_ascii=False))}
        deps[node_id] = (roots & ids) - {node_id}
    return deps


def never_run_nodes(graph: dict[str, Any], *, entry_is_root: bool = False) -> set[str]:
    """这一层图里**一定不会被执行**的节点:engine.execute_graph 的 is_entry + incoming_active,只是条件分支两支都算可能走。

    - 入口:开始节点永远是;`entry_is_root`(循环体 / 子图,执行器就这么跑体)时没有入边的节点也是。
    - 其余节点「可能跑」:决定它跑不跑的那几条入边(有控制边只看控制边,一条都没有才看数据边)里,有一条的来源
      可能跑。从条件节点出发的边,真假哪一支都可能走。
    - `{{…}}` 引用不在其中:它只管先后(见 reference_dependencies),不会让被引用的节点运行 —— 顶层一个只靠引用
      挂着的节点,引擎每次都跳过它。

    两头有一头不在这一层的连线不算入边(和引擎同一条)。和画布的 analyze.ts neverRunNodes 跑同一份语料
    contracts/workflow-never-run-cases.json。
    """
    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    ids = {str(node.get("id", "")) for node in nodes}
    incoming: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in ids}
    for edge in graph.get("edges") or []:
        if isinstance(edge, dict) and str(edge.get("source")) in ids and str(edge.get("target")) in ids:
            incoming[str(edge.get("target"))].append(edge)
    #: 谁跑了就能让谁跑:来源 → 由它决定跑不跑的下游。
    unlocks: dict[str, set[str]] = {}
    for target, edges in incoming.items():
        control = [edge for edge in edges if str(edge.get("kind", "")) != "data"]
        for edge in control or edges:
            unlocks.setdefault(str(edge.get("source")), set()).add(target)
    may_run = {
        str(node.get("id", "")) for node in nodes
        if node.get("type") == "start" or (entry_is_root and not incoming[str(node.get("id", ""))])
    }
    frontier = list(may_run)
    while frontier:
        for target in unlocks.get(frontier.pop(), ()):
            if target not in may_run:
                may_run.add(target)
                frontier.append(target)
    return ids - may_run


def never_run_references(graph: dict[str, Any], *, entry_is_root: bool = False) -> list[dict[str, Any]]:
    """**会跑的节点引用了一定不会跑的节点** —— 那个引用跑起来只会是空串,而工作流照样报成功。

    引用:这一层会插值的 `{{节点.…}}`(和 reference_dependencies 同一口径:代码字段、容器的 body / output / condition
    不算),加上数据边 —— 规范化把整格一条的引用升级成的就是数据边,两种写法是同一件事。

    只管「一定不会跑」的(见 never_run_nodes);被引用的节点在条件分支里、可能跑可能不跑的不算 —— 另一支没跑时
    引用出来是空串,那是作者有意为之。引用方自己也不会跑的不算:没有谁会拿着空值往下走。

    按被引用的节点归拢:`[{source, referenced_by, refs}]`,都排好序。和画布的 analyze.ts neverRunReferences 跑同一份
    语料 contracts/workflow-never-run-cases.json。
    """
    never = never_run_nodes(graph, entry_is_root=entry_is_root)
    if not never:
        return []
    found: dict[str, tuple[set[str], set[str]]] = {}

    def note(source: str, target: str, ref: str) -> None:
        referenced_by, refs = found.setdefault(source, (set(), set()))
        referenced_by.add(target)
        refs.add(ref)

    nodes = [node for node in graph.get("nodes") or [] if isinstance(node, dict)]
    ids = {str(node.get("id", "")) for node in nodes}
    for node in nodes:
        node_id = str(node.get("id", ""))
        if node_id in never:
            continue
        for parts in _outer_references(node):
            if parts[0] in never and parts[0] != node_id:
                note(parts[0], node_id, "{{" + ".".join(parts) + "}}")
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict) or str(edge.get("kind", "")) != "data":
            continue
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source in never and target in ids and target not in never:
            output = str(edge.get("source_output") or "")
            note(source, target, "{{" + (f"{source}.{output}" if output else source) + "}}")
    return [
        {"source": source, "referenced_by": sorted(referenced_by), "refs": sorted(refs)}
        for source, (referenced_by, refs) in sorted(found.items())
    ]


def topo_order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """稳定拓扑序(按 nodes 数组原顺序打破平局)。连线和引用都算依赖。假定 graph 已通过校验。"""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    indegree = {str(n["id"]): 0 for n in nodes}
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
        indegree[str(edge["target"])] += 1
    for target, sources in reference_dependencies(graph).items():
        for source in sources:
            adjacency.setdefault(source, []).append(target)
            indegree[target] += 1
    order: list[dict[str, Any]] = []
    by_id = {str(n["id"]): n for n in nodes}
    ready = [str(n["id"]) for n in nodes if indegree[str(n["id"])] == 0]
    while ready:
        current = ready.pop(0)
        order.append(by_id[current])
        for nxt in adjacency.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return order


def as_text(value: Any) -> str:
    """一个值**当文字用**时写成什么。插值把值嵌进文字、节点把整个值当文字用,都走这一处。

    结构化的值(对象、列表)和布尔、空值写成 JSON —— 此前是 `str()`,于是对象嵌进 HTTP 请求体
    是 Python 的 repr(`{'ok': True, 'n': None}`),没有一个 JSON 解析器认它;布尔写成
    `True`,和条件节点右边照 JSON 习惯写的 `true` 永远对不上。`None` 是"没有值",写成空串。
    """
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (bool, dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _lookup(ref: str, context: dict[str, dict[str, Any]]) -> Any:
    """Walk a dotted path: {{node.key}}, and nested {{loop.item.name}} / {{q.assets.0.id}}."""
    parts = ref.split(".")
    if parts[0] not in context:
        # A miss must read as empty, not as the {} sentinel used to walk the path. Returning
        # the dict meant a typo'd `condition` made _truthy({}) false — so a while loop ran
        # exactly once and looked deliberate — while a typo'd `left` with op `not_empty`
        # evaluated TRUE, because str({}) is non-empty. The branch silently inverted.
        return ""
    current: Any = context[parts[0]]
    for part in parts[1:]:
        if isinstance(current, dict):
            current = current.get(part, "")
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
    return current


def interpolate(value: Any, context: dict[str, dict[str, Any]]) -> Any:
    """把字符串里的 {{node.key}} 换成上下文值;整串引用时保留原类型。"""
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, context) for v in value]
    if not isinstance(value, str):
        return value
    whole = VARIABLE_RE.fullmatch(value.strip())
    if whole:
        return _lookup(whole.group(1), context)
    return VARIABLE_RE.sub(lambda m: as_text(_lookup(m.group(1), context)), value)


def interpolate_json_text(template: str, context: dict[str, dict[str, Any]]) -> Any:
    """一段**写成 JSON 的模板**(HTTP 请求体)按 JSON 的规矩插值:结果仍是合法的 JSON。

    普通插值把值原样拼进文字 —— `{"prompt": "{{llm.text}}"}` 碰上一段带引号或换行的回答,
    请求体当场成了坏的 JSON。这里看引用落在哪:

    - 在一对引号**里面**:填转义过的字符串内容(`"` → `\"`、换行 → `\n`);
    - 在引号**外面**(`"count": {{q.count}}`):填这个值的 JSON 字面量(数字、对象、带引号的字符串)。

    整串引用照旧保留原类型(交出去时 as_text 写成 JSON);不是 JSON 的模板(纯文本请求体)按普通插值。

    「是不是 JSON」看**把引用换成占位之后解不解析得了**,不看开头是不是 `{` / `[`:此前
    `{{llm.text}}\n\n来自 Mosael`、`[告警] {{msg}}` 这样的纯文本请求体也被当成 JSON,引用被填成带引号的
    JSON 字面量,发出去的文字多了一对引号、换行成了 `\n`。
    """
    stripped = template.strip()
    if VARIABLE_RE.fullmatch(stripped) or not _is_json_template(stripped):
        return interpolate(template, context)
    pieces: list[str] = []
    in_string = escaped = False
    cursor = 0
    for match in VARIABLE_RE.finditer(template):
        segment = template[cursor:match.start()]
        for char in segment:
            if escaped:
                escaped = False
            elif in_string and char == "\\":
                escaped = True
            elif char == '"':
                in_string = not in_string
        pieces.append(segment)
        value = _lookup(match.group(1), context)
        if in_string:
            pieces.append(json.dumps(as_text(value), ensure_ascii=False)[1:-1])
        else:
            pieces.append(json.dumps(value, ensure_ascii=False, default=str))
        cursor = match.end()
    pieces.append(template[cursor:])
    return "".join(pieces)


def _is_json_template(template: str) -> bool:
    """引用换成一个数字占位之后是一段合法的 JSON 吗。引用在引号里外都成立(`"0"` / `0`)。"""
    try:
        json.loads(VARIABLE_RE.sub("0", template))
    except ValueError:
        return False
    return True
