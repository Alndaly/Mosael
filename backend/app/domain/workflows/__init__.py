"""工作流内核(Coze/Dify 式)。

一个工作流 = 节点(nodes) + 连线(edges) 的 DAG,存为 JSON graph:

    {
      "nodes": [{"id": "n1", "type": "start", "name": "wfNode_start",
                  "position": {"x": 0, "y": 0}, "config": {...}}, ...],
      "edges": [{"id": "e1", "source": "n1", "target": "n2"}, ...]
    }

节点 config 里的字符串支持 `{{节点id.输出名}}` 变量引用,执行时按拓扑序
求值。定时任务与智能体都以工作流为执行单元。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Workflow

# 包的公开面不变:节点表、图规则、错误类型都还能从 app.domain.workflows 直接拿(几十处调用方这么写)。
from app.domain.workflows.errors import WorkflowDomainError  # noqa: F401
from app.domain.workflows.graph_rules import (  # noqa: F401
    _MAX_GRAPH_SCAN_DEPTH,
    BRANCHING_NODE_TYPES,
    EXTERNAL_NODE_TYPES,
    INTERNAL_NODE_TYPES,
    NESTED_BODY_RAW_KEYS,
    NESTED_BODY_TYPES,
    VARIABLE_RE,
    _body_label,
    _is_external,
    _nodes_of_types,
    one_of_errors,
    _plugin_types,
    _unresolvable_body_refs,
    as_text,
    external_nodes_in_graph,
    interpolate,
    never_run_nodes,
    never_run_references,
    reference_dependencies,
    start_option_violations,
    topo_order,
    validate_body_graph,
    validate_graph,
    with_run_params,
)
from app.domain.workflows.node_types import (  # noqa: F401
    _DATA_TYPE_BY_NAME,
    _FIELD_LABELS,
    _OUTPUT_DATA_TYPES,
    _RAW_JSON_FIELDS,
    _WORKFLOW_DATA_TYPES,
    EXTERNAL_ID,
    NODE_CATEGORIES,
    NODE_TYPES,
    WIRING_CATEGORIES,
    _generation_parameters_help,
    _humanize_field_key,
    _source_assets_help,
    available_node_types,
    config_data_type,
    config_editor,
    config_entity_kinds,
    config_label,
    config_media,
    field_name,
    output_data_type,
    output_label,
)


def list_workflows(db: Session, workspace_id: str) -> list[Workflow]:
    return list(
        db.scalars(select(Workflow).where(Workflow.workspace_id == workspace_id).order_by(Workflow.updated_at.desc()))
    )


def create_workflow(
    db: Session,
    *,
    workspace_id: str,
    name: str,
    description: str = "",
    graph: dict[str, Any] | None = None,
    source: str = "create",
    created_by: str | None,
    revision_note: str = "",
) -> Workflow:
    graph = graph if graph is not None else default_graph()
    from app.domain.workflows.normalization import normalize_graph

    extra_types = _plugin_types(db)
    graph = normalize_graph(graph, node_types={**NODE_TYPES, **extra_types})
    # 保存放行「还没配完」:必填缺失交给就绪检查与运行时,否则新节点存不下来。
    errors = validate_graph(graph, require_config=False, allow_missing_start=True, extra_types=extra_types)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    workflow = Workflow(workspace_id=workspace_id, name=name, description=description, graph=graph)
    db.add(workflow)
    from app.domain.workflows.revisions import create_initial_revision

    create_initial_revision(
        db,
        workflow,
        source=source,
        created_by=created_by,
        note=revision_note,
    )
    db.flush()
    db.refresh(workflow)
    return workflow


def _checked_graph(db: Session, graph: Any) -> dict[str, Any]:
    """落库前的同一道:规范化 + 校验(草稿级,允许缺配置、缺开始节点)。"""
    from app.domain.workflows.normalization import normalize_graph

    extra_types = _plugin_types(db)
    normalized = normalize_graph(graph, node_types={**NODE_TYPES, **extra_types})
    errors = validate_graph(normalized, require_config=False, allow_missing_start=True, extra_types=extra_types)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    return normalized


def update_workflow(
    db: Session,
    workflow: Workflow,
    changes: dict[str, Any],
    *,
    base_graph_hash: str | None = None,
    source: str = "edit",
    created_by: str | None,
    revision_note: str = "",
) -> Workflow:
    """改名、改描述、存整份图。

    **存整份图必须带底子**(`base_graph_hash`,调用方读到的那份图的摘要):整份快照不知道别人
    刚改了什么,底子对不上就撞 `WorkflowGraphConflict`,而不是把别人的写入静默盖掉。
    只改自己那一处的写入走 `edit_workflow_graph`。
    """
    from app.domain.workflows.revisions import commit_graph_revision, replace_graph

    graph = changes.get("graph")
    if graph is not None:
        if base_graph_hash is None:
            raise WorkflowDomainError("wfErr_graphBaseMissing")
        # 图先落:撞了冲突时名字和描述也一起不动,不留半次写入。
        commit_graph_revision(
            db,
            workflow,
            replace_graph(_checked_graph(db, graph), base_graph_hash=base_graph_hash),
            source=source,
            created_by=created_by,
            note=revision_note,
        )
    if changes.get("name"):
        workflow.name = changes["name"]
    if changes.get("description") is not None:
        workflow.description = changes["description"]
    db.flush()
    db.refresh(workflow)
    return workflow


def edit_workflow_graph(
    db: Session,
    workflow: Workflow,
    change: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    source: str,
    created_by: str | None,
) -> Workflow:
    """只改图里自己那一处(按算子改图):落在**最新那份图**上,撞上并发写入就重读再合。

    和画板的 `_merge_into_latest` 同一条 —— 从最新那份出发重做一遍,不会盖掉任何人。
    """
    from app.domain.workflows.revisions import commit_graph_revision

    commit_graph_revision(
        db,
        workflow,
        lambda current: _checked_graph(db, change(current)),
        source=source,
        created_by=created_by,
    )
    db.flush()
    db.refresh(workflow)
    return workflow


def default_graph() -> dict[str, Any]:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 80, "y": 160}, "config": {"params": {}}}
        ],
        "edges": [],
    }
