"""工作流文件(`.mosael-workflow.json`)的信封格式与校验。

信封:`{format, version, workflow_revision, graph_hash, name, description, graph}`。桌面端导出它、
导入它(backend 的 routes/workflows),社区收它、发它 —— 认不认这份文件,两边是同一条规则。

**这里只管信封和图的骨架**(节点是带 id 与 type 的对象、连线指向存在的节点)。节点类型认不认得、
配置合不合法,要看桌面端那张节点注册表(随版本变,还有插件节点),那是导入时 `create_workflow`
的事,不在格式这一层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mosael_formats.i18n import FormatError

FORMAT = "mosael-workflow"
VERSION = 1
SUFFIX = f".{FORMAT}.json"

#: 名字、简介的长度上限(和桌面端工作流表的列宽一致)。
MAX_NAME_CHARS = 180
MAX_DESCRIPTION_CHARS = 2000

#: 会**执行一段调用方写的代码**的节点类型:`code` 跑 Python,`browser_evaluate` 在浏览器页面里跑脚本。
#: 社区详情页据此醒目标出「含运行代码节点」。桌面端节点注册表里凡是带 `type: "code"` 配置项的节点
#: 都得在这里 —— backend/tests/test_formats_code_nodes_match_registry.py 盯着两边一致。
CODE_NODE_TYPES = frozenset({"code", "browser_evaluate"})

#: 插件节点的类型前缀:`plugin.<插件 id>.<工具>`。
PLUGIN_NODE_PREFIX = "plugin."

#: 内嵌子图放在节点配置的这个键下(循环体 / subgraph)。
BODY_KEY = "body"


class WorkflowFileError(FormatError):
    """不是一份能认的工作流文件。"""


@dataclass(frozen=True)
class WorkflowFile:
    name: str
    description: str
    version: int
    graph: dict[str, Any]
    workflow_revision: int | None = None
    graph_hash: str = ""


@dataclass(frozen=True)
class GraphSummary:
    """一张图里有什么 —— 社区的列表与详情用。内嵌子图(循环体、subgraph)里的节点也算。"""

    node_count: int
    node_types: list[str] = field(default_factory=list)
    code_node_types: list[str] = field(default_factory=list)
    plugin_ids: list[str] = field(default_factory=list)

    @property
    def has_code(self) -> bool:
        return bool(self.code_node_types)


def read_workflow_file(data: Any) -> WorkflowFile:
    """一个已经 `json.loads` 过的对象 → 规整过的信封。不是工作流文件、版本比我们新,都在这里说。

    名字为空时给空串,由调用方决定用什么占位(桌面端给「导入的工作流」,社区要求作者填标题)。
    """
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("graph"), dict):
        raise WorkflowFileError("workflowFileErr_notWorkflowFile")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version > VERSION:
        raise WorkflowFileError("workflowFileErr_tooNew", version=version)
    revision = data.get("workflow_revision")
    return WorkflowFile(
        name=str(data.get("name") or "").strip()[:MAX_NAME_CHARS],
        description=str(data.get("description") or "")[:MAX_DESCRIPTION_CHARS],
        version=version,
        graph=data["graph"],
        workflow_revision=revision if isinstance(revision, int) and not isinstance(revision, bool) else None,
        graph_hash=str(data.get("graph_hash") or ""),
    )


def check_graph(graph: dict[str, Any], *, where: str = "graph") -> None:
    """图的骨架:`nodes` 是对象列表,每个有不重复的字符串 id 和字符串 type;`edges` 的两端都是存在的节点。

    桌面端导入时由 `create_workflow` 连同节点注册表一起查得更细,这里不重复那一层;社区收文件时
    没有注册表,只能查到这一层 —— 但至少挡住一份打不开的图。
    """
    nodes = graph.get("nodes")
    edges = graph.get("edges", [])
    if not isinstance(nodes, list):
        raise WorkflowFileError("workflowFileErr_badGraph", detail=f"{where}.nodes")
    if not isinstance(edges, list):
        raise WorkflowFileError("workflowFileErr_badGraph", detail=f"{where}.edges")
    ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            raise WorkflowFileError("workflowFileErr_badGraph", detail=f"{where}.nodes[{index}].id")
        if not isinstance(node.get("type"), str) or not node["type"]:
            raise WorkflowFileError("workflowFileErr_badGraph", detail=f"{where}.nodes[{index}].type")
        if node["id"] in ids:
            raise WorkflowFileError("workflowFileErr_badGraph", detail=f"{where}.nodes[{index}].id = {node['id']}")
        ids.add(node["id"])
        body = (node.get("config") or {}).get(BODY_KEY) if isinstance(node.get("config"), dict) else None
        if isinstance(body, dict):
            check_graph(body, where=f"{where}.nodes[{index}].config.body")
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict) or edge.get("source") not in ids or edge.get("target") not in ids:
            raise WorkflowFileError("workflowFileErr_badGraph", detail=f"{where}.edges[{index}]")


def summarize_graph(graph: dict[str, Any]) -> GraphSummary:
    """数节点、认出运行代码的节点和要用到的插件。先过 `check_graph`。"""
    count = 0
    types: set[str] = set()
    code: set[str] = set()
    plugins: set[str] = set()

    def walk(one: dict[str, Any]) -> None:
        nonlocal count
        for node in one.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            count += 1
            node_type = str(node.get("type") or "")
            types.add(node_type)
            if node_type in CODE_NODE_TYPES:
                code.add(node_type)
            if node_type.startswith(PLUGIN_NODE_PREFIX):
                plugin_id = node_type[len(PLUGIN_NODE_PREFIX):].rpartition(".")[0]
                if plugin_id:
                    plugins.add(plugin_id)
            config = node.get("config")
            body = config.get(BODY_KEY) if isinstance(config, dict) else None
            if isinstance(body, dict):
                walk(body)

    walk(graph)
    return GraphSummary(
        node_count=count, node_types=sorted(types), code_node_types=sorted(code), plugin_ids=sorted(plugins)
    )


__all__ = [
    "BODY_KEY",
    "CODE_NODE_TYPES",
    "FORMAT",
    "GraphSummary",
    "MAX_DESCRIPTION_CHARS",
    "MAX_NAME_CHARS",
    "PLUGIN_NODE_PREFIX",
    "SUFFIX",
    "VERSION",
    "WorkflowFile",
    "WorkflowFileError",
    "check_graph",
    "read_workflow_file",
    "summarize_graph",
]
