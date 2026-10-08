"""工作流里存着的**被取代的插件工具节点**,改写成取代它的那个工具。

插件在运行时报出的工具可以声明它**取代**了哪个老工具的哪一种用法(见 docs/PLUGIN_MANIFEST 的
「运行时报出的工具」):

    "replaces": {
      "tool": "run_workflow",                       // 老工具
      "match": {"workflow": "portrait.json"},       // 老节点的配置里这几格是这些值,才算「这一种用法」
      "rename": {"image": "image_10", "values.3.steps": "steps_3", "prompt": "prompt"},
      "drop_if": {"wait": true}                     // 这几格是这个值时可以直接丢(那是老工具的默认)
    }

取代好几种老用法时是一组这样的对象(ComfyUI 的工作流工具还取代它自己以前按路径哈希起的名字)。

ComfyUI 插件就是这样:以前一个 `run_workflow` + `workflow: "portrait.json"`,现在每张工作流有自己的工具
(`wf_…`,入参就是那张图自己的节点),`run_workflow` 本身删掉了。存着的老节点**自动迁过去**,不留兼容分支:

- 配置里的每一格(字典按 `键.子键` 展开、列表按 `键.序号` 展开)要么在 `rename` 里,要么新工具的入参里有同名的
  一格,要么按 `drop_if` 可以丢;
- **有一格对不上时看老工具还在不在**(那个连接此刻的工具里有没有它):还在,就不改这个节点 —— 宁可留着能跑的
  老节点,也不丢用户填的值;**已经不在了**(插件删掉了它),老节点本来就跑不起来,那就改过去、把没有位置的几格
  丢掉,并记进这一版修订的说明里(上一版修订原样留着,丢的值在历史里查得到);
- 连到这个节点的数据边(`target_input`)按同一张表改名;对不上的一条同上:老工具还在就不改,不在了就拆掉;
- **下游对它输出的引用**(从它连出去的数据边 `source_output`、别的节点里的 `{{节点.输出…}}`)也要对得上:新工具有同名的
  输出口,或者 `replaces.outputs` 里写了改成哪个(`{"assets": "asset_ids"}`)。对不上的同上:老工具还在就不改;
  不在了就改过去,连出去的那条数据边拆掉、模板引用原样留着(它会取到空),都记进修订说明;
- 节点上选了连接(`instance_id`)的,按那个连接报的清单改;没选的,只有所有连接给出同一个答案时才改;
- 改过的工作流追加一版修订(`source = "migration"`),作者沿用上一版 —— 机械改写不换担保人。

什么时候跑:插件的工具清单每刷新一次(`dynamic_tools.on_refreshed`),以及每次启动(对账步骤
`rewrite-replaced-plugin-tools`,用上次缓存的清单 —— ComfyUI 没开也迁得动)。清单里不再有 `replaces`、
或者库里已经没有老节点时什么都不做,所以重复跑是安全的。

画板上存着的节点产出者(内容格的能力 `form.abilities`、空格子上的生成器 `form.producer`)是同一种
`node:plugin.<包>.<工具>` + 配置,由画板域用同一个 `rewrite_node` 改(domain/boards/plugin_references ——
画板的数据归画板域写)。
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PluginInstance, Workflow, WorkflowRevisionAttestation
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX, declared_outputs, parse_node_type

logger = logging.getLogger(__name__)

MISSING = object()


class Replacement:
    def __init__(self, package_id: str, instance_id: str, new_tool: str, spec: dict[str, Any], properties: set[str],
                 *, retired: bool = False, outputs: list[str] | None = None, only_chosen: bool = False):
        self.package_id = package_id
        self.instance_id = instance_id
        self.new_tool = new_tool
        self.old_tool = str(spec.get("tool") or "")
        self.match = spec.get("match") if isinstance(spec.get("match"), dict) else {}
        self.rename = spec.get("rename") if isinstance(spec.get("rename"), dict) else {}
        self.drop_if = spec.get("drop_if") if isinstance(spec.get("drop_if"), dict) else {}
        #: 老工具的输出口 → 新工具的哪个口(`replaces.outputs`)。没写的按同名接。
        self.output_rename = spec.get("outputs") if isinstance(spec.get("outputs"), dict) else {}
        self.properties = properties
        #: 新工具作为节点有哪些输出口(plugins.nodes.declared_outputs)。
        self.outputs = set(outputs or ["output"])
        #: 老工具在这个连接上**已经不在了**:对不上的格子丢掉,而不是留下一个跑不起来的节点。
        self.retired = retired
        #: 只改**选了这个连接**的节点:没选连接的节点跑的时候可能落到另一条也有这个工具名的连接上,在那里它不是这件事。
        self.only_chosen = only_chosen

    def target(self, path: str) -> Any:
        if path in self.rename:
            return self.rename[path] if isinstance(self.rename[path], str) and self.rename[path] else MISSING
        return path if path in self.properties else MISSING

    def output(self, name: str) -> Any:
        """下游引用的老输出口 `name` 在新工具上叫什么;没有这个口是 MISSING。"""
        renamed = self.output_rename.get(name)
        if isinstance(renamed, str) and renamed:
            return renamed if renamed in self.outputs else MISSING
        return name if name in self.outputs else MISSING


def _current_tools(db: Session, instance: PluginInstance) -> set[str] | None:
    """这个连接此刻有哪些工具(清单里声明的 + 运行时报出的)。读不出来(包记录没了、清单坏了)回 None ——
    那就当老工具还在,照严的来:说不准的时候不丢用户的值。"""
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.tools import all_tools

    try:
        return {tool["name"] for tool in all_tools(db, instance)}
    except (PluginDomainError, ValueError):  # ValueError 含清单解析的 ManifestError
        return None


def replacements(db: Session) -> list[Replacement]:
    """所有连接报出的工具里,声明了 `replaces` 的那些。"""
    found: list[Replacement] = []
    for instance in db.scalars(select(PluginInstance)):
        specs_by_tool: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for tool in instance.discovered_tools or []:
            if not isinstance(tool, dict):
                continue
            raw = tool.get("replaces")
            specs = [raw] if isinstance(raw, dict) else [one for one in raw if isinstance(one, dict)] if isinstance(raw, list) else []
            if specs:
                specs_by_tool.append((tool, specs))
        if not specs_by_tool:
            continue
        current = _current_tools(db, instance)
        for tool, specs in specs_by_tool:
            schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
            properties = set((schema.get("properties") or {}).keys())
            found.extend(
                Replacement(instance.package_id, instance.id, str(tool["name"]), spec, properties,
                            retired=current is not None and str(spec.get("tool") or "") not in current,
                            outputs=declared_outputs(tool))
                for spec in specs
            )
    return [one for one in found if one.old_tool]


def _given(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _flatten(config: dict[str, Any]) -> list[tuple[str, Any]]:
    flat: list[tuple[str, Any]] = []
    for key, value in config.items():
        if isinstance(value, dict) and value:
            flat.extend((f"{key}.{sub}", item) for sub, item in value.items())
        elif isinstance(value, list) and value:
            flat.extend((f"{key}.{index}", item) for index, item in enumerate(value))
        else:
            flat.append((key, value))
    return flat


def convert(config: dict[str, Any], replacement: Replacement, dropped: list[str] | None = None) -> dict[str, Any] | None:
    """老节点的配置 → 新工具的配置。不是这一种用法,或者有一格对不上而老工具还在,回 None。

    老工具已经不在了(`retired`)时,对不上的那几格丢掉,名字记进 `dropped`(给了的话)。
    """
    if any(config.get(key) != value for key, value in replacement.match.items()):
        return None
    converted: dict[str, Any] = {}
    unplaced: list[str] = []
    if config.get("instance_id"):
        converted["instance_id"] = config["instance_id"]
    rest = {key: value for key, value in config.items() if key != "instance_id" and key not in replacement.match}
    for path, value in _flatten(rest):
        if not _given(value):
            continue
        if path in replacement.drop_if and replacement.drop_if[path] == value:
            continue
        target = replacement.target(path)
        if target is MISSING:
            if not replacement.retired:
                return None
            unplaced.append(path)
            continue
        converted[target] = value
    if dropped is not None:
        dropped.extend(unplaced)
    return converted


def rewrite_node(
    node_type: str, config: dict[str, Any], found: list[Replacement], dropped: list[str] | None = None,
) -> tuple[str, dict[str, Any], Replacement] | None:
    """一个节点(类型 + 配置)该不该改、改成什么。**所有候选给出同一个答案**才改。丢掉的格子记进 `dropped`。"""
    parsed = parse_node_type(node_type)
    if parsed is None:
        return None
    package_id, tool_name = parsed
    chosen = str(config.get("instance_id") or "")
    answers: dict[tuple[str, str], tuple[dict[str, Any], Replacement, list[str]]] = {}
    for replacement in found:
        if replacement.package_id != package_id or replacement.old_tool != tool_name:
            continue
        if (chosen or replacement.only_chosen) and replacement.instance_id != chosen:
            continue
        unplaced: list[str] = []
        converted = convert(config, replacement, unplaced)
        if converted is not None:
            answers[(replacement.new_tool, repr(sorted(converted.items(), key=lambda item: item[0])))] = (
                converted, replacement, unplaced)
    if len({key[0] for key in answers}) != 1 or len(answers) != 1:
        return None
    (new_tool, _), (converted, replacement, unplaced) = next(iter(answers.items()))
    if dropped is not None:
        dropped.extend(unplaced)
    return f"{PLUGIN_NODE_PREFIX}{package_id}.{new_tool}", converted, replacement


def _data_edge_into(edge: Any, node_id: Any) -> bool:
    return (isinstance(edge, dict) and edge.get("target") == node_id and edge.get("kind") == "data"
            and bool(edge.get("target_input")))


_REFERENCE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def _references_to(value: Any, node_id: str) -> set[str]:
    """一格配置(连同里面的字典、列表,不进嵌套的子图)里引用了 `node_id` 的哪几个输出口。"""
    found: set[str] = set()
    if isinstance(value, str):
        for match in _REFERENCE.finditer(value):
            parts = match.group(1).split(".")
            if len(parts) >= 2 and parts[0] == node_id:
                found.add(parts[1])
    elif isinstance(value, dict) and not isinstance(value.get("nodes"), list):
        for one in value.values():
            found |= _references_to(one, node_id)
    elif isinstance(value, list):
        for one in value:
            found |= _references_to(one, node_id)
    return found


def _rename_references(value: Any, node_id: str, renames: dict[str, str]) -> Any:
    """把 `{{node_id.老口…}}` 改成 `{{node_id.新口…}}`(不进嵌套的子图)。"""
    if isinstance(value, str):
        def swap(match: re.Match[str]) -> str:
            parts = match.group(1).split(".")
            if len(parts) >= 2 and parts[0] == node_id and parts[1] in renames:
                return "{{" + ".".join([node_id, renames[parts[1]], *parts[2:]]) + "}}"
            return match.group(0)

        return _REFERENCE.sub(swap, value)
    if isinstance(value, dict) and not isinstance(value.get("nodes"), list):
        return {key: _rename_references(one, node_id, renames) for key, one in value.items()}
    if isinstance(value, list):
        return [_rename_references(one, node_id, renames) for one in value]
    return value


def _deep_references(value: Any, node_id: str, outputs: set[str]) -> set[str]:
    """一格配置里对 `node_id` 的 `outputs` 这几个口、**带子路径**的引用(`n.assets.0.asset_id`),不进嵌套的子图。"""
    found: set[str] = set()
    if isinstance(value, str):
        for match in _REFERENCE.finditer(value):
            parts = match.group(1).split(".")
            if len(parts) > 2 and parts[0] == node_id and parts[1] in outputs:
                found.add(match.group(1))
    elif isinstance(value, dict) and not isinstance(value.get("nodes"), list):
        for one in value.values():
            found |= _deep_references(one, node_id, outputs)
    elif isinstance(value, list):
        for one in value:
            found |= _deep_references(one, node_id, outputs)
    return found


def _inner_keys(node: dict[str, Any]) -> tuple[str, ...]:
    """容器节点(循环 / 子图)配置里属于**体内**作用域的几格(NESTED_BODY_RAW_KEYS):`output` / `condition` 里的
    `{{p1.x}}` 指的是体里的 p1,不是这一层同名的那个。和 normalization、reference_dependencies 同一条界线。"""
    from app.domain.workflows import NESTED_BODY_RAW_KEYS, NESTED_BODY_TYPES

    return NESTED_BODY_RAW_KEYS if str(node.get("type") or "") in NESTED_BODY_TYPES else ()


def _this_scope(node: dict[str, Any]) -> dict[str, Any]:
    """一个节点的配置里**属于这一层**的那几格(去掉容器的体内作用域)。"""
    inner = _inner_keys(node)
    return {key: value for key, value in (node.get("config") or {}).items() if key not in inner}


def _used_outputs(graph: dict[str, Any], node_id: str, outside: dict[str, Any]) -> tuple[set[str], set[str]]:
    """下游用了这个节点的哪几个输出口:(从它连出去的数据边, 别的节点里的模板引用)。

    模板引用只算**同一个作用域**里的:这一层别的节点(容器的体内那几格不算 —— 那是体里的作用域),加上
    `outside` —— 这一层是一个容器的体时,容器自己的 output / condition 就是体内的下游。
    """
    by_edge = {
        str(edge.get("source_output") or "") for edge in graph.get("edges") or []
        if isinstance(edge, dict) and edge.get("source") == node_id and edge.get("kind") == "data"
        and edge.get("source_output")
    }
    by_template = _references_to(outside, node_id)
    for other in graph.get("nodes") or []:
        if isinstance(other, dict) and other.get("id") != node_id:
            by_template |= _references_to(_this_scope(other), node_id)
    return by_edge, by_template


def rewrite_graph(
    graph: dict[str, Any], found: list[Replacement], dropped: list[str] | None = None,
    unchecked: list[str] | None = None,
) -> dict[str, Any]:
    """一张图(连同循环体 / 子图)里能改的节点都改掉;连进来的数据边跟着改入参名,下游对它输出的引用跟着改口名。

    老工具已经不在了时,没有位置的格子、数据边和下游引用丢掉;给了 `dropped` 就把它们记成 `节点 id.格子` /
    `节点 id.格子(连线)` / `节点 id.输出(下游连线)` / `节点 id.输出(下游引用)`。

    改了口名、引用又带着子路径的(`{{n.assets.0.asset_id}}` → `{{n.asset_ids.0.asset_id}}`):新口的值不一定是
    同一个形状(老口是一串对象,新口是一串 id),子路径对不上时取到的是空 —— 改写看不出来,给了 `unchecked`
    就记成 `老引用 → 新引用`,让人核对。
    """
    return _rewrite_scope(graph, found, dropped, {}, unchecked)[0]


def _rewrite_scope(
    graph: dict[str, Any], found: list[Replacement], dropped: list[str] | None, outside: dict[str, Any],
    unchecked: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """改一层作用域。`outside` 是这一层作为容器的体时、容器自己那几格体内作用域的配置(output / condition):
    它们是体里节点的下游,改口名时一起改,改过的跟着返回。"""
    if not isinstance(graph, dict):
        return graph, outside
    renamed: dict[str, Replacement] = {}
    #: 改过的节点 → 它的输出口改名(老 → 新),和对不上、要拆掉的那几条连出去的数据边的口名
    output_renames: dict[str, dict[str, str]] = {}
    loose_outputs: dict[str, set[str]] = {}
    nodes: list[Any] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            nodes.append(node)
            continue
        config = dict(node.get("config") or {})
        inner_keys = _inner_keys(node)
        for key, value in list(config.items()):
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                # 容器自己的 output / condition 和体里的节点同一个作用域:体里的口改了名,它们跟着改
                inner = {one: config[one] for one in inner_keys if one != key and one in config} if key == "body" else {}
                config[key], inner = _rewrite_scope(value, found, dropped, inner, unchecked)
                config.update(inner)
        unplaced: list[str] = []
        result = rewrite_node(str(node.get("type") or ""), config, found, unplaced)
        if result is None:
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
            continue
        new_type, converted, replacement = result
        node_id = str(node.get("id"))
        loose = [str(edge["target_input"]) for edge in graph.get("edges") or []
                 if _data_edge_into(edge, node.get("id")) and replacement.target(str(edge["target_input"])) is MISSING]
        by_edge, by_template = _used_outputs(graph, node_id, outside)
        unmatched = {name for name in by_edge | by_template if replacement.output(name) is MISSING}
        if (loose or unmatched) and not replacement.retired:
            nodes.append({**node, "config": config})
            continue
        renamed[node_id] = replacement
        output_renames[node_id] = {
            name: replacement.output(name) for name in (by_edge | by_template) - unmatched
            if replacement.output(name) != name
        }
        loose_outputs[node_id] = unmatched & by_edge
        if dropped is not None:
            dropped.extend(f"{node_id}.{path}" for path in unplaced)
            dropped.extend(f"{node_id}.{field}(连线)" for field in loose)
            dropped.extend(f"{node_id}.{name}(下游连线)" for name in sorted(unmatched & by_edge))
            dropped.extend(f"{node_id}.{name}(下游引用)" for name in sorted(unmatched & by_template))
        nodes.append({**node, "type": new_type, "config": converted})
    for node_id, renames in output_renames.items():
        if renames and unchecked is not None:
            scopes = [outside, *(_this_scope(one) for one in nodes if isinstance(one, dict) and one.get("id") != node_id)]
            deep = set().union(*(_deep_references(one, node_id, set(renames)) for one in scopes))
            for path in sorted(deep):
                reference = "{{" + path + "}}"
                unchecked.append(f"{reference} → {_rename_references(reference, node_id, renames)}")
        if renames:
            nodes = [
                {**one, "config": {**(one.get("config") or {}), **_rename_references(_this_scope(one), node_id, renames)}}
                if isinstance(one, dict) and one.get("id") != node_id else one
                for one in nodes
            ]
            outside = _rename_references(outside, node_id, renames)
    edges = []
    for edge in graph.get("edges") or []:
        replacement = renamed.get(str(edge.get("target"))) if isinstance(edge, dict) else None
        if replacement is not None and _data_edge_into(edge, edge.get("target")):
            target = replacement.target(str(edge["target_input"]))
            if target is MISSING:
                continue  # 老工具已经不在了,这一路在新工具上没有接口
            edge = {**edge, "target_input": target}
        source = str(edge.get("source")) if isinstance(edge, dict) else ""
        if source in renamed and edge.get("kind") == "data" and edge.get("source_output"):
            output = str(edge["source_output"])
            if output in loose_outputs[source]:
                continue  # 新工具上没有这个输出口,这条连出去的线接不上了
            edge = {**edge, "source_output": output_renames[source].get(output, output)}
        edges.append(edge)
    rewritten = {**graph, "nodes": nodes, "edges": edges} if "edges" in graph else {**graph, "nodes": nodes}
    return rewritten, outside


def rewrite_replaced_tools(db: Session) -> int:
    """把库里所有工作流里能改的老插件节点改掉。返回改了几个工作流。"""
    found = replacements(db)
    if not found:
        return 0
    old_types = {f"{PLUGIN_NODE_PREFIX}{one.package_id}.{one.old_tool}" for one in found}
    changed = 0
    for workflow in db.scalars(select(Workflow)):
        if not any(old in str(workflow.graph) for old in old_types):
            continue
        dropped: list[str] = []
        unchecked: list[str] = []
        rewritten = rewrite_graph(deepcopy(workflow.graph), found, dropped, unchecked)
        if rewritten == workflow.graph:
            continue
        note = "插件工具换了新写法:改用取代它的那个工具"
        if dropped:
            # 丢了什么要说出来:老工具已经不在了,这几格在新工具上没有位置(上一版修订里还看得到原值)
            note += "。老工具已经没有了,这些在新工具上对不上(格子、连线、下游对它输出的引用),没带过去:" + "、".join(dropped)
            logger.info("工作流 %s 改写插件节点时丢掉了 %s", workflow.id, dropped)
        if unchecked:
            # 口改了名,引用带着子路径:新口的值形状可能不一样,取到空也不会报错 —— 说出来让人核对
            note += "。这些下游引用跟着输出口改了名,但带着子路径(新口的值未必是同一个形状,对不上会取到空),请核对:" + "、".join(unchecked)
        if _commit_mechanical_revision(db, workflow, lambda graph: rewrite_graph(graph, found), note):
            changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 个工作流里的老插件节点改写成了取代它的工具", changed)
    return changed


def _commit_mechanical_revision(db: Session, workflow: Workflow, rewrite: Any, note: str, *,
                                source: str = "migration") -> bool:
    """机械改写落一版修订(`source = "migration"`;工作流库里改名时跟着改的是 `"rename"`):作者沿用上一版,认可过上一版的人
    照样为这一版担保 —— 机械改写不该让一条跑得好好的流程停下来等人认可。不提交。"""
    from app.domain.workflows.revisions import commit_graph_revision, current_workflow_revision, revision_vouchers

    previous = current_workflow_revision(db, workflow)
    vouchers = revision_vouchers(db, previous)
    revision = commit_graph_revision(db, workflow, rewrite, source=source, created_by=previous.created_by,
                                     note=note[:2000])
    if revision is None:
        return False
    for user in vouchers - {revision.created_by}:
        db.add(WorkflowRevisionAttestation(revision_id=revision.id, user_id=user))
    return True


# ── 一次性的改名(ADR 0045,见 domain/plugins/moves) ──────────────────────────────────


def moved_tools(db: Session, instance: PluginInstance, renames: dict[str, str], *, why: str = "moved") -> list[Replacement]:
    """这个连接的工具改了名(旧工具名 → 新工具名),写成「取代」:节点类型换成新名字,配置照新工具的入参同名接 ——
    旧名字从这一版起另有所指,对不上的格子丢掉、记进修订说明(当作老用法已经不在了)。没选连接的节点,只有别的连接
    都没有这个旧工具名时才改(`only_chosen`)。

    `why="renamed"`(在工作流库里改名、挪目录,ADR 0045 修订之二):这时工具清单还没重拉,新名字不在清单上 —— 是同一张图,
    入参照旧名字那一份。"""
    tools = {str(tool.get("name")): tool for tool in instance.discovered_tools or [] if isinstance(tool, dict)}
    others = [one for one in db.scalars(select(PluginInstance).where(PluginInstance.package_id == instance.package_id,
                                                                     PluginInstance.id != instance.id))]
    found: list[Replacement] = []
    for source, target in renames.items():
        tool = tools.get(target) or (tools.get(source) if why == "renamed" else None)
        if tool is None:
            continue
        schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
        shared = any(source == str(one.get("name")) for other in others for one in other.discovered_tools or []
                     if isinstance(one, dict))
        found.append(Replacement(instance.package_id, instance.id, target, {"tool": source},
                                 set((schema.get("properties") or {}).keys()), retired=True,
                                 outputs=declared_outputs(tool), only_chosen=shared))
    return found


#: 工作流库里改了名、挪了目录,跟着改的那一版修订怎么说(ADR 0045 修订之二 D2)
_RENAMED_NOTE = "这张图在工作流库里改了名、挪了文件夹:这里选的那一张跟着改到新的名字"


def follow_moved_tools(db: Session, instance: PluginInstance, renames: dict[str, str], *, why: str = "moved") -> int:
    """工作流里选着这个连接旧工具名的节点改到新名字(`moved_tools`)。不提交。返回改了几个工作流。"""
    found = moved_tools(db, instance, renames, why=why)
    old_types = {f"{PLUGIN_NODE_PREFIX}{one.package_id}.{one.old_tool}" for one in found}
    changed = 0
    for workflow in db.scalars(select(Workflow)):
        if not any(old in str(workflow.graph) for old in old_types):
            continue
        dropped: list[str] = []
        if rewrite_graph(deepcopy(workflow.graph), found, dropped) == workflow.graph:
            continue
        note = _RENAMED_NOTE if why == "renamed" else \
            "插件的工具改了名:这个节点以前选的那件事现在叫新名字(ComfyUI 有表单的工作流,表单成了它的一个入口)"
        if dropped:
            note += "。新名字的入参里没有这几格,没带过去(以前跑的时候也不认):" + "、".join(dropped)
        if _commit_mechanical_revision(db, workflow, lambda graph: rewrite_graph(graph, found), note,
                                       source="rename" if why == "renamed" else "migration"):
            changed += 1
    return changed


def follow_moved_models(db: Session, profile_id: str, renames: dict[str, str], *, why: str = "moved") -> int:
    """工作流里选着这条连接旧模型名的(生成节点、按生成选项选模型的那几格)改到新名字。不提交。返回改了几个工作流。"""
    from app.domain.providers.moved_models import renamed

    changed = 0
    for workflow in db.scalars(select(Workflow)):
        if profile_id not in str(workflow.graph) or renamed(workflow.graph, profile_id, renames) == workflow.graph:
            continue
        note = _RENAMED_NOTE if why == "renamed" else \
            "连接上的模型改了名:这里选的那一个现在叫新名字(ComfyUI 有表单的工作流,表单成了它的一个入口)"
        if _commit_mechanical_revision(db, workflow, lambda graph: renamed(graph, profile_id, renames), note,
                                       source="rename" if why == "renamed" else "migration"):
            changed += 1
    return changed


def _after_refresh(db: Session, instance: PluginInstance) -> None:
    rewrite_replaced_tools(db)


def install() -> None:
    from app.domain.plugins import dynamic_tools, moves
    from app.domain.providers import moved_models

    dynamic_tools.on_refreshed(_after_refresh)
    moves.on_tools_moved(follow_moved_tools)
    moved_models.on_moved(follow_moved_models)


__all__ = ["MISSING", "Replacement", "convert", "follow_moved_models", "follow_moved_tools", "install", "moved_tools",
           "replacements", "rewrite_graph", "rewrite_node", "rewrite_replaced_tools"]
