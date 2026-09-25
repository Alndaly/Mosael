"""工作流和画板:建、改、跑。

**运行一张图的档位由图自己说了算** —— 图里有会伸到应用外面去的节点(发帖、请求别人的服务器、跑代码)时,
卡按最高那一档开,并且在摘要里点名(见 graphs)。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.domain.agent.confirmable.graphs import external_warning, graph_under_review
from app.domain.workflows import external_nodes_in_graph



def _workflow_in(db: Session, workspace_id: str, payload: dict[str, Any]):
    """这次要改/要跑的那张工作流,**收进这个工作区**。"""
    from app.db.models import Workflow

    workflow = db.get(Workflow, str(payload.get("workflow_id", "")))
    if workflow is None or workflow.workspace_id != workspace_id:
        raise ConfirmationError("Workflow not found in this workspace")
    return workflow



def _check_graph(db: Session, graph: object) -> None:
    """校验模型提出的这张图。

    **`extra_types` 必须带上。** 智能体完全可以用插件节点搭图(它们和内置节点在画布上没有
    区别,`plugin_node_types` 存在的全部意义就是这个)。不带的话,那个节点被判成未知类型,
    卡上报出「该插件未安装或未启用」—— 插件明明装着、开着,而用户会照着这句话去插件页找问题。
    """
    from app.domain.plugins.nodes import plugin_node_types
    from app.domain.workflows import validate_graph

    errors = validate_graph(
        graph, require_config=False, allow_missing_start=True, extra_types=plugin_node_types(db)
    )
    if errors:
        raise ConfirmationError("；".join(errors))



def _escalate_graph(db: Session, tool: str, payload: dict[str, Any]) -> str | None:
    """图里有会伸到应用外面去的节点(发帖、请求别人的服务器、跑代码)时,按最高那一档开卡。

    档位由**这次真的会落库或执行的那张图**说了算,不是由工具名说了算 —— 同一个 edit_workflow,
    加一个文本节点和加一个 code 节点不是一回事。
    """
    return "external" if external_nodes_in_graph(graph_under_review(db, tool, payload)) else None



def _validate_create_workflow(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    if not str(payload.get("name", "")).strip():
        raise ConfirmationError("create_workflow requires a name")
    if payload.get("graph") is not None:
        _check_graph(db, payload["graph"])


def _summarize_create_workflow(db: Session, payload: dict[str, Any]) -> Summary:
    nodes = len((payload.get("graph") or {}).get("nodes", []) or [])
    return "confirm_createWorkflow", {
        "name": payload.get("name", ""),
        "nodes": nodes or 1,
        "warning": external_warning(external_nodes_in_graph(graph_under_review(db, "create_workflow", payload))),
    }


def _execute_create_workflow(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.domain.workflows import create_workflow

    workflow = create_workflow(
        db,
        workspace_id=confirmation.workspace_id,
        name=str(payload["name"]),
        description=str(payload.get("description", "")),
        graph=payload.get("graph"),
        source="agent",
        created_by=actor,
    )
    return {"workflow_id": workflow.id}


def _validate_update_workflow(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    workflow = _workflow_in(db, workspace_id, payload)
    if payload.get("graph") is not None:
        _check_graph(db, payload["graph"])
        # 整份图是对着**开卡这一刻**的图审的:记下它的底子。批准之前用户又改过的话,执行时撞冲突,
        # 而不是拿这份整图把用户刚做的改动静默盖掉(和界面自动保存同一道,见 update_workflow)。
        payload["base_graph_hash"] = workflow.graph_hash


def _summarize_update_workflow(db: Session, payload: dict[str, Any]) -> Summary:
    nodes = len((payload.get("graph") or {}).get("nodes", []) or [])
    warning = external_warning(external_nodes_in_graph(graph_under_review(db, "update_workflow", payload)))
    if nodes:
        return "confirm_updateWorkflow", {"nodes": nodes, "warning": warning}
    return "confirm_updateWorkflowPlain", {"warning": warning}


def _execute_update_workflow(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Workflow
    from app.domain.workflows import update_workflow

    workflow = db.get(Workflow, str(payload["workflow_id"]))
    assert workflow is not None  # validated at request time
    update_workflow(
        db,
        workflow,
        {key: payload[key] for key in ("name", "description", "graph") if key in payload},
        base_graph_hash=payload.get("base_graph_hash"),
        source="agent",
        created_by=actor,
    )
    return {"workflow_id": workflow.id}


def _validate_edit_workflow(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.graph_ops import GRAPH_OP_KINDS, apply_graph_ops

    workflow = _workflow_in(db, workspace_id, payload)
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ConfirmationError("edit_workflow requires a non-empty operations list")
    for operation in operations:
        kind = operation.get("kind") if isinstance(operation, dict) else None
        if kind not in GRAPH_OP_KINDS:
            raise ConfirmationError(f"Unsupported workflow op: {kind}")
    # Dry-run the ops onto the current graph so malformed edits fail fast (before approval).
    try:
        preview = apply_graph_ops(workflow.graph or {}, operations)
    except WorkflowDomainError as exc:
        raise ConfirmationError(str(exc)) from exc
    _check_graph(db, preview)


def _summarize_edit_workflow(db: Session, payload: dict[str, Any]) -> Summary:
    ops = [op for op in payload.get("operations", []) if isinstance(op, dict)]
    kinds = [op.get("kind", "?") for op in ops]
    # A `code` node runs arbitrary local Python when the workflow is later run, so say so
    # here rather than leaving it to be noticed in the payload.
    adds_code = any(
        op.get("kind") == "add_node" and str(op.get("node_type") or op.get("type")) == "code" for op in ops
    )
    # code 那句更具体(点名"运行时执行本地 Python"),留着;其余外部节点走通用那句。
    warning = (fragment("confirm_editWorkflowCode") if adds_code
               else external_warning(external_nodes_in_graph(graph_under_review(db, "edit_workflow", payload))))
    return "confirm_editWorkflow", {
        "count": len(kinds),
        "kinds": ", ".join(kinds[:6]) + ("…" if len(kinds) > 6 else ""),
        "warning": warning,
    }


def _execute_edit_workflow(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Workflow
    from app.domain.workflows import edit_workflow_graph
    from app.domain.workflows.graph_ops import apply_graph_ops

    workflow = db.get(Workflow, str(payload["workflow_id"]))
    assert workflow is not None
    # 算子落在**最新那份图**上(不是开卡时的快照),撞上并发写入就在新图上重做 —— 见 edit_workflow_graph。
    edit_workflow_graph(
        db,
        workflow,
        lambda current: apply_graph_ops(current or {}, payload["operations"]),
        source="agent",
        created_by=actor,
    )
    return {"workflow_id": workflow.id, "nodes": len((workflow.graph or {}).get("nodes", []))}


def _validate_run_workflow(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    _workflow_in(db, workspace_id, payload)



def _summarize_run_workflow(db: Session, payload: dict[str, Any]) -> Summary:
    name = str(payload.get("name") or payload.get("workflow_id") or "")
    return "confirm_runWorkflow", {
        "named": fragment("confirm_workflowNamed", name=name) if name else "",
        "warning": external_warning(external_nodes_in_graph(graph_under_review(db, "run_workflow", payload))),
    }


def _execute_run_workflow(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Workflow
    from app.domain.workflows.engine import start_workflow_job

    workflow = db.get(Workflow, str(payload["workflow_id"]))
    assert workflow is not None
    job = start_workflow_job(db, workflow, created_by=actor, params=dict(payload.get("params") or {}))
    return {"job_id": job.id}


def _validate_edit_board(db: Session, workspace_id: str, payload: dict[str, Any]) -> None:
    from app.db.models import Board
    from app.domain.boards.ops import BOARD_OP_KINDS, apply_board_ops
    from app.domain.boards import BoardDomainError, check_canvas

    board = db.get(Board, str(payload.get("board_id", "")))
    if board is None or board.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_boardNotInWorkspace")
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ConfirmationError("confirmErr_editBoardNeedsOps")
    for operation in operations:
        kind = operation.get("kind") if isinstance(operation, dict) else None
        if kind not in BOARD_OP_KINDS:
            raise ConfirmationError("confirmErr_unknownBoardOp", kind=kind)
    # 先干跑一遍:写坏的算子要在**批准之前**就失败,而不是让用户点了同意才看到报错。
    # 和落库过同一道(形状 + 引用),见 boards.check_canvas。
    try:
        check_canvas(db, workspace_id, apply_board_ops(board.canvas or {}, operations), board.canvas)
    except BoardDomainError as exc:
        raise ConfirmationError(str(exc)) from exc


def _summarize_edit_board(db: Session, payload: dict[str, Any]) -> Summary:
    kinds = [op.get("kind", "?") for op in payload.get("operations", []) if isinstance(op, dict)]
    return "confirm_editBoard", {
        "count": len(kinds),
        "kinds": ", ".join(kinds[:6]) + ("…" if len(kinds) > 6 else ""),
    }


def _execute_edit_board(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    from app.db.models import Board
    from app.domain.boards.ops import apply_board_ops
    from app.domain.boards import update_board

    board = db.get(Board, str(payload["board_id"]))
    assert board is not None  # 开卡时校验过
    # 落到**批准这一刻**的画布上,而不是开卡时的那份快照 —— 这中间用户很可能还在拖东西。
    canvas = apply_board_ops(board.canvas or {}, payload["operations"])
    update_board(db, workspace_id=board.workspace_id, board_id=board.id, name=None, canvas=canvas)
    return {"board_id": board.id, "items": len(canvas.get("items", []))}

confirmable_tool(ConfirmableTool(
    name="create_workflow",
    permission="edit",
    cost="none",
    summarize=_summarize_create_workflow,
    execute=_execute_create_workflow,
    validate=_validate_create_workflow,
    escalate=_escalate_graph,
))


confirmable_tool(ConfirmableTool(
    name="update_workflow",
    permission="edit",
    cost="none",
    summarize=_summarize_update_workflow,
    execute=_execute_update_workflow,
    validate=_validate_update_workflow,
    escalate=_escalate_graph,
))


confirmable_tool(ConfirmableTool(
    name="edit_workflow",
    permission="edit",
    cost="none",
    summarize=_summarize_edit_workflow,
    execute=_execute_edit_workflow,
    validate=_validate_edit_workflow,
    escalate=_escalate_graph,
))


confirmable_tool(ConfirmableTool(
    name="run_workflow",
    permission="ai-cost",
    cost="ai",
    summarize=_summarize_run_workflow,
    execute=_execute_run_workflow,
    validate=_validate_run_workflow,
    escalate=_escalate_graph,
))


confirmable_tool(ConfirmableTool(
    name="edit_board",
    permission="edit",
    cost="none",
    summarize=_summarize_edit_board,
    execute=_execute_edit_board,
    validate=_validate_edit_board,
))


