"""工作流内核(Coze/Dify 式)。

一个工作流 = 节点(nodes) + 连线(edges) 的 DAG,存为 JSON graph:

    {
      "nodes": [{"id": "n1", "type": "start", "name": "开始",
                  "position": {"x": 0, "y": 0}, "config": {...}}, ...],
      "edges": [{"id": "e1", "source": "n1", "target": "n2"}, ...]
    }

节点 config 里的字符串支持 `{{节点id.输出名}}` 变量引用,执行时按拓扑序
求值。定时任务与智能体都以工作流为执行单元。
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workflow


class WorkflowDomainError(RuntimeError):
    pass


# 节点类型注册表:同时驱动后端校验、前端节点面板和智能体的图编辑提示。
# outputs 是节点执行后写入上下文的键;config 描述每个可配置字段。
NODE_TYPES: dict[str, dict[str, Any]] = {
    "start": {
        "label": "开始",
        "description": "工作流入口,声明输入参数(运行时可覆盖默认值)。",
        "config": {"params": {"type": "object", "description": "输入参数名 → 默认值"}},
        "outputs": ["*params"],
    },
    "llm": {
        "label": "LLM 生成",
        "description": "调用配置的 AI 供应商生成文本。",
        "config": {
            "prompt": {"type": "template", "required": True, "description": "用户提示词,支持 {{变量}}"},
            "system": {"type": "template", "description": "系统提示词"},
            "profile_id": {"type": "string", "description": "供应商配置 id,留空自动选择"},
            "model": {"type": "string", "description": "模型名,留空用配置默认"},
        },
        "outputs": ["text"],
    },
    "kb_search": {
        "label": "知识库检索",
        "description": "检索工作区知识库,输出片段文本。",
        "config": {
            "query": {"type": "template", "required": True},
            "limit": {"type": "number", "description": "返回条数,默认 5"},
        },
        "outputs": ["text", "results"],
    },
    "plugin_tool": {
        "label": "插件工具",
        "description": "调用已启用插件的纯函数工具。",
        "config": {
            "plugin_id": {"type": "string", "required": True},
            "tool_name": {"type": "string", "required": True},
            "input": {"type": "object", "description": "工具入参,值支持 {{变量}}"},
        },
        "outputs": ["output"],
    },
    "transcribe_asset": {
        "label": "素材转写",
        "description": "对音视频素材跑 ASR,输出全文。",
        "config": {"asset_id": {"type": "template", "required": True}},
        "outputs": ["text"],
    },
    "export_sequence": {
        "label": "导出时间线",
        "description": "渲染导出一条时间线,产出新素材。",
        "config": {"sequence_id": {"type": "template", "required": True}},
        "outputs": ["asset_id"],
    },
    "ai_generate": {
        "label": "AI 生成素材",
        "description": "文生图/文生视频,产出素材进素材库。",
        "config": {
            "provider": {"type": "string", "required": True},
            "model": {"type": "string", "required": True},
            "kind": {"type": "string", "required": True, "description": "image | video"},
            "prompt": {"type": "template", "required": True},
        },
        "outputs": ["asset_id", "generation_id"],
    },
    "publish": {
        "label": "发布",
        "description": "把素材发布到指定账号(本地目录 / Webhook / 演示平台)。",
        "config": {
            "account_id": {"type": "string", "required": True, "description": "发布账号 id(发布页可查)"},
            "asset_id": {"type": "template", "required": True},
            "title": {"type": "template"},
            "description": {"type": "template"},
        },
        "outputs": ["result"],
    },
}

VARIABLE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def validate_graph(graph: dict[str, Any]) -> list[str]:
    """结构校验:返回错误列表(空表 = 合法)。"""
    errors: list[str] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["graph 必须包含 nodes 与 edges 两个数组"]

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
        if node_type not in NODE_TYPES:
            errors.append(f"未知节点类型: {node_type} ({node_id})")
            continue
        if node_type == "start":
            start_count += 1
        for key, spec in NODE_TYPES[node_type]["config"].items():
            if isinstance(spec, dict) and spec.get("required"):
                value = (node.get("config") or {}).get(key)
                if value in (None, ""):
                    errors.append(f"节点 {node_id} 缺少必填配置 {key}")
    if start_count != 1:
        errors.append(f"工作流必须恰好包含 1 个开始节点(当前 {start_count} 个)")

    adjacency: dict[str, list[str]] = {}
    indegree: dict[str, int] = {node_id: 0 for node_id in seen_ids}
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in seen_ids or target not in seen_ids:
            errors.append(f"连线引用了不存在的节点: {source} → {target}")
            continue
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
        errors.append("工作流包含环路,必须是有向无环图")
    return errors


def topo_order(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """稳定拓扑序(按 nodes 数组原顺序打破平局)。假定 graph 已通过校验。"""
    nodes = list(graph.get("nodes") or [])
    edges = list(graph.get("edges") or [])
    indegree = {str(n["id"]): 0 for n in nodes}
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(str(edge["source"]), []).append(str(edge["target"]))
        indegree[str(edge["target"])] += 1
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


def interpolate(value: Any, context: dict[str, dict[str, Any]]) -> Any:
    """把字符串里的 {{node.key}} 换成上下文值;整串引用时保留原类型。"""
    if isinstance(value, dict):
        return {k: interpolate(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, context) for v in value]
    if not isinstance(value, str):
        return value

    def lookup(ref: str) -> Any:
        node_id, _, key = ref.partition(".")
        scope = context.get(node_id, {})
        return scope.get(key, "") if key else scope

    whole = VARIABLE_RE.fullmatch(value.strip())
    if whole:
        return lookup(whole.group(1))
    return VARIABLE_RE.sub(lambda m: str(lookup(m.group(1))), value)


def list_workflows(db: Session, workspace_id: str) -> list[Workflow]:
    return list(
        db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id).order_by(Workflow.updated_at.desc()))
    )


def create_workflow(
    db: Session, *, workspace_id: str, name: str, description: str = "", graph: dict[str, Any] | None = None
) -> Workflow:
    graph = graph if graph is not None else default_graph()
    errors = validate_graph(graph)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    workflow = Workflow(workspace_id=workspace_id, name=name, description=description, graph=graph)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def update_workflow(db: Session, workflow: Workflow, changes: dict[str, Any]) -> Workflow:
    if "graph" in changes and changes["graph"] is not None:
        errors = validate_graph(changes["graph"])
        if errors:
            raise WorkflowDomainError("；".join(errors))
        workflow.graph = changes["graph"]
    if changes.get("name"):
        workflow.name = changes["name"]
    if changes.get("description") is not None:
        workflow.description = changes["description"]
    db.commit()
    db.refresh(workflow)
    return workflow


def default_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 80, "y": 160}, "config": {"params": {}}}
        ],
        "edges": [],
    }
