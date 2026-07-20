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
            "preset": {
                "type": "string",
                "description": "生成风格(替代裸 temperature)",
                "options": ["precise", "balanced", "creative"],
            },
            "profile_id": {"type": "string", "description": "供应商配置 id,留空自动选择"},
            "model": {"type": "string", "description": "模型名,留空用配置默认"},
        },
        "outputs": ["text"],
    },
    "kb_search": {
        "label": "知识库检索",
        "description": "检索指定知识库,输出片段文本。",
        "config": {
            "dataset_id": {"type": "string", "description": "选择要检索的知识库(留空则用工作区内首个)"},
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
            "kind": {"type": "string", "required": True, "description": "生成类型", "options": ["image", "video"]},
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
    "condition": {
        "label": "条件分支",
        "description": "按条件把流程导向「真」或「假」分支(连线时从对应端点拉出)。",
        "config": {
            "left": {"type": "template", "required": True, "description": "左值,如 {{llm-1.text}}"},
            "op": {
                "type": "string",
                "required": True,
                "description": "比较方式",
                "options": ["equals", "not_equals", "contains", "not_contains", "empty", "not_empty", "gt", "lt"],
            },
            "right": {"type": "template", "description": "右值(empty/not_empty 不需要)"},
        },
        "outputs": ["result"],
        "branches": ["true", "false"],
    },
    "http_request": {
        "label": "HTTP 请求",
        "description": "调用外部 API,输出状态码与响应内容。",
        "config": {
            "method": {"type": "string", "description": "默认 GET", "options": ["GET", "POST", "PUT", "DELETE"]},
            "url": {"type": "template", "required": True},
            "headers": {"type": "object", "description": "请求头,值支持 {{变量}}"},
            "body": {"type": "template", "description": "请求体(POST/PUT),JSON 或纯文本"},
        },
        "outputs": ["status", "text", "json"],
    },
    "code": {
        "label": "代码",
        "description": "运行一段 Python:inputs 为入参 dict,把结果赋给 output 变量。与插件同级的本地信任沙箱。",
        "config": {
            "code": {"type": "code", "required": True, "description": "如:output = len(inputs['text'])"},
            "input": {"type": "object", "description": "入参,值支持 {{变量}}"},
        },
        "outputs": ["output"],
    },
    "template": {
        "label": "文本模板",
        "description": "把多个上游变量拼装成一段文本。",
        "config": {"template": {"type": "template", "required": True}},
        "outputs": ["text"],
    },
    "json_extract": {
        "label": "JSON 提取",
        "description": "从 JSON/对象里按点路径取值,常接在 HTTP 请求或插件工具后面。",
        "config": {
            "source": {"type": "template", "required": True, "description": "JSON 文本或 {{节点.json}}"},
            "path": {"type": "string", "description": "点路径,如 data.items.0.title;留空返回整个对象"},
        },
        "outputs": ["value", "text"],
    },
    "text_transform": {
        "label": "文本处理",
        "description": "对文本做去空白/大小写/替换/正则提取/取长度等处理。",
        "config": {
            "text": {"type": "template", "required": True},
            "op": {
                "type": "string",
                "required": True,
                "description": "处理方式",
                "options": ["trim", "upper", "lower", "replace", "regex_extract", "length"],
            },
            "find": {"type": "string", "description": "replace 的查找串 / regex_extract 的正则"},
            "replace": {"type": "string", "description": "replace 的替换串"},
        },
        "outputs": ["text", "length"],
    },
    "delay": {
        "label": "延时",
        "description": "等待若干秒再继续(限流/节流用)。",
        "config": {"seconds": {"type": "number", "description": "等待秒数,默认 1,上限 300"}},
        "outputs": ["waited"],
    },
    "synthesize_speech": {
        "label": "语音合成",
        "description": "用指定音色把文本合成为配音,产出音频素材进素材库。",
        "config": {
            "voice_id": {"type": "string", "required": True, "description": "音色 id(配音库可查)"},
            "text": {"type": "template", "required": True},
        },
        "outputs": ["asset_id"],
    },
    "notify": {
        "label": "发送通知",
        "description": "给工作区成员推送一条站内通知。",
        "config": {
            "title": {"type": "template", "required": True},
            "body": {"type": "template", "description": "通知正文"},
        },
        "outputs": ["sent"],
    },
    "translate": {
        "label": "翻译",
        "description": "把文本翻译成目标语言:Google 免费接口(无需 key)或 AI 供应商。",
        "config": {
            "text": {"type": "template", "required": True},
            "target_lang": {
                "type": "string",
                "required": True,
                "description": "目标语言",
                "options": ["en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "ru"],
            },
            "engine": {"type": "string", "description": "翻译引擎(默认 Google 免费)", "options": ["google", "ai"]},
            "profile_id": {"type": "string", "description": "engine=ai 时的供应商配置,留空自动"},
        },
        "outputs": ["text"],
    },
    "loop_foreach": {
        "label": "循环·遍历",
        "description": "对一个列表逐项运行内嵌子流程,汇总每次迭代的输出为列表。子流程内用 {{loop.item}} / {{loop.index}} 引用当前元素与序号。",
        "config": {
            "items": {
                "type": "template",
                "required": True,
                "description": "要遍历的列表,支持 {{变量}}(如 {{split_1.results}});也接受多行文本(按行拆分)",
            },
            "body": {"type": "graph", "description": "循环体子流程(在节点内编辑;子流程节点用 {{loop.item}}/{{loop.index}})"},
            "output": {
                "type": "template",
                "description": "每次迭代的输出,引用子流程节点输出(如 {{translate_1.text}});留空则输出整份子上下文",
            },
        },
        "outputs": ["results", "count"],
    },
    "loop_while": {
        "label": "循环·条件",
        "description": "反复运行内嵌子流程,直到条件不再成立(带最大次数上限防死循环)。子流程内用 {{loop.index}} 拿当前轮次;子流程里放一个「条件」节点,把它的 {{节点id.result}} 填到 condition。",
        "config": {
            "body": {"type": "graph", "description": "循环体子流程(每轮跑一遍;通常含一个条件节点决定是否继续)"},
            "condition": {
                "type": "template",
                "description": "每轮跑完后判断是否继续,引用子流程里条件节点的布尔输出(如 {{check.result}});留空则只跑一轮",
            },
            "max_iterations": {"type": "number", "description": "最大轮次(默认 50,硬上限 1000),防死循环"},
            "output": {"type": "template", "description": "每轮的输出(如 {{step.text}});留空则输出整份子上下文"},
        },
        "outputs": ["results", "count", "iterations"],
    },
    "asset_query": {
        "label": "素材筛选",
        "description": "按条件批量选出工作区里的素材(类型/名称/标签),输出素材列表 —— 常接「循环·遍历」的 items 逐个处理。",
        "config": {
            "kind": {"type": "string", "description": "素材类型", "options": ["all", "video", "image", "audio"]},
            "name_contains": {"type": "template", "description": "名称包含此关键词(留空不筛)"},
            "tags": {"type": "template", "description": "标签(逗号分隔,命中任一即选;留空不筛)"},
            "limit": {"type": "number", "description": "最多返回条数(默认 50,上限 500)"},
        },
        "outputs": ["assets", "ids", "count"],
    },
}

VARIABLE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def validate_graph(graph: dict[str, Any], *, require_start: bool = True, require_config: bool = True) -> list[str]:
    """结构校验:返回错误列表(空表 = 合法)。

    require_config=False 用于**保存**:必填字段缺失属于「还没配完」,不该拦住存盘 —— 否则配合
    实时保存,新加一个带必填项的节点就永远存不下来。缺必填由「就绪检查」提示、由运行时拦截。

    require_start=False 用于循环体子图:子图没有 start 节点(执行时由循环上下文喂入
    {{loop.item}}),无入边的节点即为入口;若子图里出现 start 则报错。
    """
    errors: list[str] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["graph 必须包含 nodes 与 edges 两个数组"]

    # 数据边(kind="data")把上游输出绑到目标输入 → 该输入即便字面量为空也算已满足。
    data_bound: set[tuple[str, str]] = {
        (str(edge.get("target", "")), str(edge.get("target_input", "")))
        for edge in edges
        if str(edge.get("kind", "")) == "data" and edge.get("target_input")
    }

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
        if require_config:
            for key, spec in NODE_TYPES[node_type]["config"].items():
                if isinstance(spec, dict) and spec.get("required"):
                    value = (node.get("config") or {}).get(key)
                    if value in (None, "") and (node_id, key) not in data_bound:
                        errors.append(f"节点 {node_id} 缺少必填配置 {key}")
    if require_start:
        if start_count != 1:
            errors.append(f"工作流必须恰好包含 1 个开始节点(当前 {start_count} 个)")
    elif start_count > 0:
        errors.append("循环体子图不能包含开始节点")

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
        if node_types.get(source) == "condition" and handle not in (None, "true", "false"):
            errors.append(f"条件节点的分支端点必须是 true/false: {source}")
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


def validate_body_graph(body: dict[str, Any]) -> list[str]:
    """循环体子图校验:必须非空、无 start 节点、其余同 validate_graph。"""
    nodes = body.get("nodes") if isinstance(body, dict) else None
    if not isinstance(nodes, list) or not nodes:
        return ["循环体不能为空,至少要有一个节点"]
    return validate_graph(body, require_start=False)


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
        # Walk a dotted path: {{node.key}}, and nested {{loop.item.name}} / {{q.assets.0.id}}.
        parts = ref.split(".")
        current: Any = context.get(parts[0], {})
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
    # 保存放行「还没配完」:必填缺失交给就绪检查与运行时,否则新节点存不下来。
    errors = validate_graph(graph, require_config=False)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    workflow = Workflow(workspace_id=workspace_id, name=name, description=description, graph=graph)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def update_workflow(db: Session, workflow: Workflow, changes: dict[str, Any]) -> Workflow:
    if "graph" in changes and changes["graph"] is not None:
        errors = validate_graph(changes["graph"], require_config=False)
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
