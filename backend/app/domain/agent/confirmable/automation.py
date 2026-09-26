"""工作流和画板:建、改、跑。

**运行一张图的档位由图自己说了算** —— 图里有会伸到应用外面去的节点(发帖、请求别人的服务器、跑代码)时,
卡按最高那一档开,并且在摘要里点名(见 graphs)。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.effects import needs_card, permission_for, warning_key
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



def _validate_create_workflow(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
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


def _validate_update_workflow(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
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


def _validate_edit_workflow(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
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


def _validate_run_workflow(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
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


def _board_in(db: Session, workspace_id: str, payload: dict[str, Any]):
    """这次要改/要跑的那张画板,**收进这个工作区**。"""
    from app.db.models import Board

    board = db.get(Board, str(payload.get("board_id", "")))
    if board is None or board.workspace_id != workspace_id:
        raise ConfirmationError("confirmErr_boardNotInWorkspace")
    return board


def _validate_edit_board(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain.boards.ops import BOARD_OP_KINDS, apply_board_ops
    from app.domain.boards import BoardDomainError, check_canvas, producers

    board = _board_in(db, workspace_id, payload)
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ConfirmationError("confirmErr_editBoardNeedsOps")
    for operation in operations:
        kind = operation.get("kind") if isinstance(operation, dict) else None
        if kind not in BOARD_OP_KINDS:
            raise ConfirmationError("confirmErr_unknownBoardOp", kind=kind)
    # 先干跑一遍:写坏的算子要在**批准之前**就失败,而不是让用户点了同意才看到报错。
    # 和落库过同一道(形状 + 引用),见 boards.check_canvas;这次写下的表单再过一遍注册表
    # (工具在不在、绑定接不接得上),和界面、运行是同一张表,见 boards.producers.check_forms。
    before = board.canvas or {}
    _mark_abilities(db, operations, actor)
    try:
        after = apply_board_ops(before, operations)
        check_canvas(db, workspace_id, after, board.canvas)
        producers.check_forms(db, after, producers.written_forms(before, after), actor)
    except BoardDomainError as exc:
        raise ConfirmationError(str(exc)) from exc


def _mark_abilities(db: Session, operations: list[Any], actor: str | None) -> None:
    """`set_form` 写的是一格的**一项能力**的设置,还是那一格自己的表单:按注册表判(这个产出者是不是一项能力,
    boards.transforms.board_role),写回算子上的 `ability` —— **覆盖**,不由调用方自己说。执行时落到批准那一刻的
    画布上,读的就是这一份判定(批准的人未必接着同一个插件,判法不能跟着人变)。"""
    from app.domain.boards import producers
    from app.domain.boards.transforms import ABILITY

    registry = {one.id: one for one in producers.list_producers(db, actor)}
    for operation in operations:
        if isinstance(operation, dict) and operation.get("kind") == "set_form":
            found = registry.get(str(operation.get("producer") or ""))
            operation["ability"] = found is not None and found.role == ABILITY


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

def _run_request(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None):
    """照画布上**现在**那一格拼一次运行:它存着的表单(或它的那一项能力的设置),它自己的位置,这张板当前的版本。

    `payload["producer"]` 点名这一格的一项**能力**(音频格上的转写、便签上的翻译)时,跑的是那一项,设置读
    `form.abilities[producer]`(没存过就是空的 —— 必填的在干跑时说出来);没点名(或点的就是它自己的产出者)
    跑的是这一格自己的产出者。`payload["ability"]` 由开卡时的干跑写回(见 _validate_run_board_item),
    执行时照它认 —— 开卡之后那一格换了自己的产出者,就不是批准的那一件。

    版本取当前的,因为智能体不是拿着一份旧快照在改画布 —— 它要跑的就是此刻画布上的那一格;
    「这一格正在跑」照样由 run 那一侧挡(见 actions._ensure_slot_ready)。
    """
    from app.domain.boards import producers
    from app.domain.boards.canvas import item_not_found
    from app.domain.boards.producer_ids import runs_from_draft

    board = _board_in(db, workspace_id, payload)
    item_id = str(payload.get("item_id") or "")
    item = next((one for one in (board.canvas or {}).get("items") or [] if str(one.get("id")) == item_id), None)
    if item is None:
        raise ConfirmationError.relay(item_not_found(item_id))
    form = dict(item.get("form") or {})
    own = str(form.pop("producer", "") or "")
    abilities = form.pop("abilities", None) or {}
    wanted = str(payload.get("producer") or "") or own
    #: 开卡之后照卡上写回的判定;开卡时(还没有这一样)照点名的是不是它自己的产出者。
    ability = bool(payload["ability"]) if "ability" in payload else wanted != own
    if ability:
        # 这一格的一项能力:设置存在宿主上;跑的是节点(能不能挂在这种格子上、是不是能力由 producers 那一侧问)。
        producer = wanted
        form = dict(abilities.get(producer) or {})
        if not runs_from_draft(producer):
            raise ConfirmationError("confirmErr_runBoardItemNotTool", item_id=item_id)
    else:
        producer = own
        # 只跑存着的表单就是运行那一份的格子:空格子上的生成器、3D 场景格(渲白模)。图片/视频/音频槽和便签上
        # 内置产出者的表单是各自面板的形状(提示词、模型、图例……),拼成一次运行是面板的事;替人拼一份面板
        # 没见过的请求,跑出来的不是他在面板上看到的那一件。
        if not runs_from_draft(producer):
            raise ConfirmationError("confirmErr_runBoardItemNotTool", item_id=item_id)
    return board, item, producers.RunRequest(
        workspace_id=workspace_id,
        board_id=board.id,
        item_id=item_id,
        kind=str(item.get("kind") or ""),
        x=float(item.get("x") or 0),
        y=float(item.get("y") or 0),
        base_revision=int(board.revision or 0),
        actor_id=actor or "",
        producer=producer,
        form=form,
    )


def _validate_run_board_item(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    """开卡之前把这次运行干跑一遍,把卡上要说的事实写回 payload。

    **写回的每一样都是覆盖,不是缺省**:`effects` 决定这次要不要问人、按哪一档问(见 needs_card /
    escalate),它不能由调用方在 payload 里自己带。
    """
    from app.core.i18n import is_message_key
    from app.domain.boards import BoardDomainError, producers

    payload.pop("ability", None)
    board, item, request = _run_request(db, workspace_id, payload, actor)
    try:
        producer, facts = producers.dry_run(db, request)
    except BoardDomainError as exc:
        raise ConfirmationError(str(exc)) from exc
    from app.domain.boards.transforms import ABILITY

    #: 跑的是这一格的一项能力(不是它自己的产出者):执行时照它读设置(见 _run_request)。点名的得真是一项能力 ——
    #: 空格子的填法(生成器)当成能力跑,就会把产出填进一格已经有内容的格子里。
    ability = request.producer != str((item.get("form") or {}).get("producer") or "")
    if ability and producer.role != ABILITY:
        raise ConfirmationError("confirmErr_runBoardItemNotTool", item_id=request.item_id)
    label = str((producer.meta or {}).get("label") or producer.id)
    payload.update({
        "producer": producer.id,
        "ability": ability,
        "effects": producer.effects,
        "tool": {"key": label} if is_message_key(label) else {"text": label},
        "board_name": board.name,
        "item_title": str(item.get("title") or ""),
        "connection": str(facts.get("connection") or ""),
    })


def _needs_card_run_board_item(db: Session, payload: dict[str, Any]) -> bool:
    """不花钱、不出门的工具直接跑;花钱的、对外有后果的、在本机跑代码的等人点(ADR 0021 决定 2)。

    判据和智能体在对话里直接调插件工具**是同一条**(domain/effects)。
    """
    return needs_card(payload.get("effects"))


def _escalate_run_board_item(db: Session, tool: str, payload: dict[str, Any]) -> str | None:
    """按工具的后果开卡:花钱的算 ai-cost(自动档里有连开上限),对外的、跑代码的算 external(自动档也回到人)。"""
    return permission_for(payload.get("effects"))


def _summarize_run_board_item(db: Session, payload: dict[str, Any]) -> Summary:
    tool = payload.get("tool") or {}
    warning = warning_key(payload.get("effects"))
    connection = str(payload.get("connection") or "")
    title = str(payload.get("item_title") or "")
    return "confirm_runBoardItem", {
        "tool": fragment(tool["key"]) if tool.get("key") else str(tool.get("text") or payload.get("producer") or ""),
        "board": str(payload.get("board_name") or ""),
        "item": fragment("confirm_boardItemNamed", name=title) if title else "",
        "via": fragment("confirm_boardRunVia", name=connection) if connection else "",
        "warning": fragment(warning) if warning else "",
    }


def _execute_run_board_item(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    """批准之后跑:**同一个** producers.run(界面点运行走的那一个),执行者是批准的人。

    插件工具用的是批准者**自己**的连接(和共享画板上谁点运行用谁的连接同一条,决定 1);他在这个
    工作区里得有这个工具要的权限。卡开出来之后那一格换了工具,就不跑 —— 他批准的不是这一个。
    """
    from app.db.models import User
    from app.domain.boards import producers
    from app.domain.permissions import ensure_workspace_perm

    payload = confirmation.payload
    _board, _item, request = _run_request(db, confirmation.workspace_id, payload, actor)
    if request.producer != payload.get("producer"):
        raise ConfirmationError("confirmErr_boardItemChanged", item_id=request.item_id)
    user = db.get(User, actor or "")
    if user is None:
        raise ConfirmationError("confirmErr_noApprover")
    producer = producers.get_producer(db, request.producer, user.id)
    ensure_workspace_perm(db, user, confirmation.workspace_id, producer.permission)
    board = producers.run(db, request)
    item = next(one for one in (board.canvas or {}).get("items") or [] if str(one.get("id")) == request.item_id)
    return {
        "board_id": board.id,
        "item_id": request.item_id,
        "producer": request.producer,
        "job_id": (item.get("run") or {}).get("job_id"),
    }


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


confirmable_tool(ConfirmableTool(
    name="run_board_item",
    #: 下限。实际那一档按工具的后果升(escalate);只读的根本不问人(needs_card)。
    permission="edit",
    cost="none",
    summarize=_summarize_run_board_item,
    execute=_execute_run_board_item,
    validate=_validate_run_board_item,
    escalate=_escalate_run_board_item,
    needs_card=_needs_card_run_board_item,
))
