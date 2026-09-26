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
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PluginInstance, Workflow, WorkflowRevisionAttestation
from app.domain.plugins.nodes import PLUGIN_NODE_PREFIX, parse_node_type

logger = logging.getLogger(__name__)

MISSING = object()


class Replacement:
    def __init__(self, package_id: str, instance_id: str, new_tool: str, spec: dict[str, Any], properties: set[str],
                 *, retired: bool = False):
        self.package_id = package_id
        self.instance_id = instance_id
        self.new_tool = new_tool
        self.old_tool = str(spec.get("tool") or "")
        self.match = spec.get("match") if isinstance(spec.get("match"), dict) else {}
        self.rename = spec.get("rename") if isinstance(spec.get("rename"), dict) else {}
        self.drop_if = spec.get("drop_if") if isinstance(spec.get("drop_if"), dict) else {}
        self.properties = properties
        #: 老工具在这个连接上**已经不在了**:对不上的格子丢掉,而不是留下一个跑不起来的节点。
        self.retired = retired

    def target(self, path: str) -> Any:
        if path in self.rename:
            return self.rename[path] if isinstance(self.rename[path], str) and self.rename[path] else MISSING
        return path if path in self.properties else MISSING


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
                            retired=current is not None and str(spec.get("tool") or "") not in current)
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
        if chosen and replacement.instance_id != chosen:
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


def rewrite_graph(graph: dict[str, Any], found: list[Replacement], dropped: list[str] | None = None) -> dict[str, Any]:
    """一张图(连同循环体 / 子图)里能改的节点都改掉;连到它们的数据边跟着改名。

    老工具已经不在了时,没有位置的格子和数据边丢掉;给了 `dropped` 就把它们记成 `节点 id.格子` /
    `节点 id.格子(连线)`。
    """
    if not isinstance(graph, dict):
        return graph
    renamed: dict[str, Replacement] = {}
    nodes: list[Any] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            nodes.append(node)
            continue
        config = dict(node.get("config") or {})
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(value.get("nodes"), list):
                config[key] = rewrite_graph(value, found, dropped)
        unplaced: list[str] = []
        result = rewrite_node(str(node.get("type") or ""), config, found, unplaced)
        if result is None:
            nodes.append({**node, "config": config} if config != (node.get("config") or {}) else node)
            continue
        new_type, converted, replacement = result
        loose = [str(edge["target_input"]) for edge in graph.get("edges") or []
                 if _data_edge_into(edge, node.get("id")) and replacement.target(str(edge["target_input"])) is MISSING]
        if loose and not replacement.retired:
            nodes.append({**node, "config": config})
            continue
        renamed[str(node.get("id"))] = replacement
        if dropped is not None:
            dropped.extend(f"{node.get('id')}.{path}" for path in unplaced)
            dropped.extend(f"{node.get('id')}.{field}(连线)" for field in loose)
        nodes.append({**node, "type": new_type, "config": converted})
    edges = []
    for edge in graph.get("edges") or []:
        replacement = renamed.get(str(edge.get("target"))) if isinstance(edge, dict) else None
        if replacement is not None and _data_edge_into(edge, edge.get("target")):
            target = replacement.target(str(edge["target_input"]))
            if target is MISSING:
                continue  # 老工具已经不在了,这一路在新工具上没有接口
            edge = {**edge, "target_input": target}
        edges.append(edge)
    return {**graph, "nodes": nodes, "edges": edges} if "edges" in graph else {**graph, "nodes": nodes}


def rewrite_replaced_tools(db: Session) -> int:
    """把库里所有工作流里能改的老插件节点改掉。返回改了几个工作流。"""
    from app.domain.workflows.revisions import commit_graph_revision, current_workflow_revision, revision_vouchers

    found = replacements(db)
    if not found:
        return 0
    old_types = {f"{PLUGIN_NODE_PREFIX}{one.package_id}.{one.old_tool}" for one in found}
    changed = 0
    for workflow in db.scalars(select(Workflow)):
        if not any(old in str(workflow.graph) for old in old_types):
            continue
        dropped: list[str] = []
        rewritten = rewrite_graph(deepcopy(workflow.graph), found, dropped)
        if rewritten == workflow.graph:
            continue
        previous = current_workflow_revision(db, workflow)
        vouchers = revision_vouchers(db, previous)
        note = "插件工具换了新写法:改用取代它的那个工具"
        if dropped:
            # 丢了什么要说出来:老工具已经不在了,这几格在新工具上没有位置(上一版修订里还看得到原值)
            note += "。老工具已经没有了,这几格在新工具里没有位置、没带过去:" + "、".join(dropped)
            logger.info("工作流 %s 改写插件节点时丢掉了 %s", workflow.id, dropped)
        revision = commit_graph_revision(
            db, workflow, lambda graph: rewrite_graph(graph, found), source="migration", created_by=previous.created_by,
            note=note[:2000],
        )
        if revision is not None:
            # 认可过上一版的人照样为这一版担保:机械改写不该让一条跑得好好的流程停下来等人认可
            for user in vouchers - {revision.created_by}:
                db.add(WorkflowRevisionAttestation(revision_id=revision.id, user_id=user))
            changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 个工作流里的老插件节点改写成了取代它的工具", changed)
    return changed


def _after_refresh(db: Session, instance: PluginInstance) -> None:
    rewrite_replaced_tools(db)


def install() -> None:
    from app.domain.plugins import dynamic_tools

    dynamic_tools.on_refreshed(_after_refresh)


__all__ = ["MISSING", "Replacement", "convert", "install", "replacements", "rewrite_graph", "rewrite_node", "rewrite_replaced_tools"]
