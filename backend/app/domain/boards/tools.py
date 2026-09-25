"""工具格:在画板上跑一个工作流节点(插件工具、挑过的内置节点),产出落成右边新的几格(ADR 0021 P2)。

**不自己实现任何能力。** 跑的是工作流那张执行器注册表里的同一个执行器
(`workflows.executors.get_executor`),拿到的作用域是画板自己的(BoardScope:工作区、
`board:<id>`、画板名)—— 不伪造一个工作流。执行者是谁跟着任务走(`jobs.current_actor`):
任务线程由 `jobs.dispatch_job` 起,父任务就是这一轮 `board_run`,于是节点里派生的子任务
(转写、分离、调子工作流)都挂在它下面,取消它就一并停下;插件进程登记在它名下,取消就被杀掉。

画板在这里只多做三件自己的事:

· **上游 → 输入**(resolve_bindings):字段绑定的是上游哪几格,值在运行这一刻从画布上取 ——
  便签给字、文档给正文、图片/视频/音频给素材、3D 场景给场景 id。
· **产出 → 格子**(board_outputs):按节点声明的输出类型把返回值归一成画板认的那几种产出
  (见 canvas.outputs_of),回执再把它们摆成右边新的几格。
· **谁的连接**:插件工具只用**点运行的那个人**自己接的连接(plugins.nodes.resolve_instance)——
  共享画板上存着别人选的连接 id,照着跑就是拿别人的密钥花别人的额度。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Board
from app.domain.boards.actions import BoardInputError
from app.domain.boards.canvas import get_board, receipt_to_item
from app.domain.jobs import create_job, dispatch_job, reset_receipt, set_receipt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoardScope:
    """节点跑在**谁名下**(workflows.executors.RunScope 那三样)。

    `id` 带前缀 `board:`:执行器拿它做防递归、通知指回去之类的事,和工作流 id 撞不上。
    """

    workspace_id: str
    id: str
    name: str


# ── 上游 → 输入 ─────────────────────────────────────────────────────────────


#: 一个字段能接哪几种上游格子。按字段装的是什么(workflows.config_data_type)分:
#: 素材字段接媒体格,场景字段接 3D 场景,能随手写字的字段(模板 / 文本、没有固定选项)接便签和文档。
#: 数字、下拉、对象这几种不接 —— 画布上没有哪一格的产出天然是它们。
_SOURCE_KINDS = {
    "asset": ("image", "video", "audio"),
    "scene": ("scene",),
    "text": ("note", "document"),
}


def binding_sink(key: str, spec: Any) -> str | None:
    """这个字段从上游接的是哪一种值:`"asset"` / `"scene"` / `"text"`;接不了回 None。

    **前端不另写一份**:工具清单(`GET /api/boards/producers`)给每个字段带上 `board_sources`
    (见 bindable_kinds),面板照它列上游。
    """
    from app.domain.workflows import config_data_type

    if not isinstance(spec, dict):
        return None
    data_type = config_data_type(key, spec)
    if data_type in ("asset", "scene"):
        return data_type
    if data_type not in ("", "text", "any"):
        return None
    if spec.get("type") not in ("template", "string") or spec.get("options") or spec.get("options_from"):
        return None
    if spec.get("editor"):
        # 有专用控件的字段(挑笔记、挑场景模型)不是随手写字的地方。
        return None
    return "text"


def bindable_kinds(key: str, spec: Any) -> list[str]:
    """这个字段能接哪几种上游格子(画板项的 kind)。给界面列绑定用。"""
    sink = binding_sink(key, spec)
    return list(_SOURCE_KINDS[sink]) if sink else []


def _is_list_field(key: str, spec: dict[str, Any]) -> bool:
    """素材字段收一份还是一串。`asset_ids` 这种复数名收一串(和 config_data_type 的命名约定一致)。"""
    return key == "asset_ids" or key.endswith("_asset_ids")


def _value_of(db: Session, workspace_id: str, source: dict[str, Any], sink: str) -> str | None:
    """上游一格在这种字段里给出什么值。给不出(种类不对、还没有产出)回 None。"""
    kind = source.get("kind")
    if kind not in _SOURCE_KINDS[sink]:
        return None
    if sink == "text":
        if kind == "note":
            return str(source.get("text") or "")
        if not source.get("note_id"):
            return None
        from app.domain.notes import read_reference

        #: 文档给的是**钉住的那一版**的正文(和画布上看到的一致),不是最新版。
        return str(read_reference(db, workspace_id, source["note_id"], source.get("note_revision"))["markdown"])
    if sink == "scene":
        return str(source.get("scene_id") or "") or None
    return str(source.get("asset_id") or "") or None


def check_bindings(
    canvas: dict[str, Any],
    item_id: str,
    specs: dict[str, Any],
    bindings: dict[str, list[dict[str, str]]],
    tool: str,
) -> None:
    """**写**绑定时(替人填表单,如智能体的 edit_board)问的那几件事,说不通就抛 BoardInputError。

    和运行时(resolve_bindings)判的是同一张表 —— 哪个字段接什么(binding_sink)、哪几种格子给得出
    (_SOURCE_KINDS,也就是面板上 `board_sources` 的来历),只是运行时对说不通的那几条**不吭声地
    跳过**(节点升级删了字段、上游还没生成出来,都不该让一次运行失败),而写的时候说清楚:这是一个
    正在写的错,不是一份放旧了的表单。

    · 字段得是这个工具声明过的、能接上游的;
    · 上游那一格得在画布上、**有一根连到这一格的线**(线不在的绑定,落库时 normalize 会摘掉 ——
      写进去的东西悄悄没了,比当场说「先连线」难查得多);
    · 那一格的种类给得出这种值(便签给不了素材)。
    """
    canvas_items = {str(one.get("id")): one for one in canvas.get("items") or []}
    wired = {(str(edge.get("source")), str(edge.get("target"))) for edge in canvas.get("edges") or []}
    for field, refs in bindings.items():
        spec = specs.get(field)
        if not isinstance(spec, dict):
            raise BoardInputError("boardErr_bindingUnknownField", tool=tool, field=field,
                                  fields=", ".join(key for key in specs if binding_sink(key, specs[key])) or "-")
        sink = binding_sink(field, spec)
        if sink is None:
            raise BoardInputError("boardErr_bindingFieldNotBindable", tool=tool, field=field)
        for ref in refs:
            source_id = str(ref.get("from") or "").strip()
            source = canvas_items.get(source_id)
            if source is None:
                raise BoardInputError("boardErr_bindingSourceMissing", field=field, source=source_id)
            if (source_id, item_id) not in wired:
                raise BoardInputError("boardErr_bindingNotWired", field=field, source=source_id, item_id=item_id)
            if source.get("kind") not in _SOURCE_KINDS[sink]:
                raise BoardInputError("boardErr_bindingKindMismatch", field=field, source=source_id,
                                      kind=str(source.get("kind")), kinds=", ".join(_SOURCE_KINDS[sink]))


def resolve_bindings(
    db: Session,
    board: Board,
    item_id: str,
    specs: dict[str, Any],
    config: dict[str, Any],
    bindings: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    """把绑定换成值,返回这一轮交给执行器的配置(不改表单上存的那份)。

    **按连线的先后**取,不按绑定里写的顺序:画布上「谁先连进来」是用户看得见、改得动的顺序。
    多张便签接进同一个文字字段,正文之间空一行拼起来;素材字段收一份的取第一份。
    字段不在节点声明里(节点升级后删掉了)就不管它;上游那一格给不出值(还没生成出来)就当没接。
    """
    canvas = board.canvas or {}
    by_id = {str(one.get("id")): one for one in canvas.get("items") or []}
    order = [str(edge.get("source")) for edge in canvas.get("edges") or [] if edge.get("target") == item_id]
    resolved = dict(config)
    for field, refs in bindings.items():
        spec = specs.get(field)
        sink = binding_sink(field, spec)
        if sink is None:
            continue
        wanted = {ref["from"] for ref in refs}
        values = [
            value
            for source_id in order
            if source_id in wanted and source_id in by_id
            for value in [_value_of(db, board.workspace_id, by_id[source_id], sink)]
            if value is not None
        ]
        if not values:
            continue
        if sink == "text":
            resolved[field] = "\n\n".join(values)
        elif sink == "asset" and _is_list_field(field, spec):
            resolved[field] = values
        else:
            resolved[field] = values[0]
    return resolved


# ── 产出 → 格子 ─────────────────────────────────────────────────────────────


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _sniff(value: Any) -> list[dict[str, Any]]:
    """没声明类型的一个输出,按值猜它是什么。

    插件交出的文件(`asset_id` + `asset_name`,见 plugins.tools._collect_artifact)是素材,
    其余字段另成一份 JSON;字符串、数是文字;列表逐项猜(一个列表 → 几格);别的是 JSON。
    """
    if _empty(value):
        return []
    if isinstance(value, str):
        return [{"type": "text", "text": value}]
    if isinstance(value, bool):
        return [{"type": "text", "text": "true" if value else "false"}]
    if isinstance(value, (int, float)):
        return [{"type": "text", "text": str(value)}]
    if isinstance(value, dict) and isinstance(value.get("asset_id"), str) and value["asset_id"]:
        rest = {key: one for key, one in value.items() if key not in ("asset_id", "asset_name") and not _empty(one)}
        return [{"type": "asset", "asset_id": value["asset_id"]}, *([{"type": "json", "value": rest}] if rest else [])]
    if isinstance(value, list):
        return [one for element in value for one in _sniff(element)]
    return [{"type": "json", "value": value}]


def board_outputs(meta: dict[str, Any], output: dict[str, Any]) -> list[dict[str, Any]]:
    """执行器的返回值 → 画板认的产出(`[{"type": "asset"|"text"|"json", …}]`,见 canvas.outputs_of)。

    按节点**声明**的输出和类型分(workflows.output_data_type —— 和工作流连线认的是同一份):
    素材输出是素材(一串 id 就是几份),文字、数是文字,JSON 是 JSON。只有一个没声明的 `output`
    (插件工具的缺省)或类型是 any 的输出才按值猜。只落 `board_outputs` 点名的那几个(缺省全部)。
    空值不落 —— 一个没用上的「尾帧」不该在画布上占一格空便签。
    """
    from app.domain.workflows import output_data_type

    declared = [str(name) for name in meta.get("outputs") or ["output"]]
    wanted = [name for name in (meta.get("board_outputs") or declared) if name in declared]
    produced: list[dict[str, Any]] = []
    for name in wanted:
        value = output.get(name)
        if _empty(value):
            continue
        data_type = output_data_type(name, meta)
        if data_type == "asset":
            ids = value if isinstance(value, list) else [value]
            produced.extend({"type": "asset", "asset_id": str(one)} for one in ids if isinstance(one, str) and one)
        elif data_type in ("text", "number", "sequence"):
            produced.append({"type": "text", "text": value if isinstance(value, str) else str(value)})
        elif data_type == "json":
            produced.append({"type": "json", "value": value})
        else:
            produced.extend(_sniff(value))
    return produced


# ── 运行 ────────────────────────────────────────────────────────────────────


def prepare_node_run(
    db: Session,
    *,
    request: Any,
    node_type: str,
    meta: dict[str, Any],
    config: dict[str, Any],
    bindings: dict[str, list[dict[str, str]]],
) -> tuple[Board, dict[str, Any]]:
    """起任务之前的全部检查,**不写任何东西**;返回画板和这一轮交给执行器的配置。

    该在花钱之前失败的都在这里失败(调用方收到 400,工具格不进「在跑」):版本对不上、这一格在跑、
    插件工具没有这个人自己的连接、数字字段填的不是数、绑定的文档取不到。

    单独成一步,因为「开卡之前先干跑一遍」(智能体的 run_board_item)问的就是这些 —— 注定起不了
    任务的卡没有让人去批的道理;而它和真跑走的是同一个函数,两边说的不会是两套话。
    """
    from app.domain.boards.actions import _ensure_slot_ready
    from app.domain.workflows.binding import check_number_fields

    _ensure_slot_ready(db, request.workspace_id, request.slot)
    board = get_board(db, request.workspace_id, request.board_id)
    resolved = resolve_bindings(db, board, request.item_id, dict(meta.get("config") or {}), config, bindings)
    resolved = check_number_fields(node_type, resolved)
    _check_plugin_connection(db, node_type, resolved, request.actor_id)
    return board, resolved


def run_node_on_board(
    db: Session,
    *,
    request: Any,
    node_type: str,
    meta: dict[str, Any],
    config: dict[str, Any],
    bindings: dict[str, list[dict[str, str]]],
    label: str,
) -> Board:
    """在工具格上跑一次节点。**顺序**和另外几个产出者一样:问版本和忙闲 → 建任务 → 摆占位 → 起任务。"""
    from app.domain.boards.actions import _pending

    board, resolved = prepare_node_run(db, request=request, node_type=node_type, meta=meta, config=config,
                                       bindings=bindings)

    token = set_receipt(receipt_to_item(request.board_id, request.item_id))
    try:
        job = create_job(
            db,
            workspace_id=request.workspace_id,
            kind="board_run",
            created_by=request.actor_id,
            payload={"board_id": request.board_id, "item_id": request.item_id, "producer": request.producer,
                     "subject": label},
            message="jobMsg_boardRunQueued",
            message_params={"name": label},
        )
    finally:
        reset_receipt(token)
    db.commit()
    placed = _pending(
        db, request.workspace_id, request.slot, actor_id=request.actor_id, kind="action",
        producer=request.producer, job_id=job.id,
        #: 表单存的是用户填的那份(绑定原样、连接原样),不是这一轮取出来的值 —— 下一次运行时
        #: 上游变了,取到的就是新的。
        form={"config": dict(config), "bindings": {field: list(refs) for field, refs in bindings.items()}},
    )
    scope = BoardScope(workspace_id=request.workspace_id, id=f"board:{board.id}", name=board.name)
    job_id = job.id
    dispatch_job(db, job, lambda: _run_in_job(job_id, node_type, meta, scope, resolved, label))
    return placed


def _check_plugin_connection(db: Session, node_type: str, config: dict[str, Any], actor_id: str) -> None:
    """插件工具:点运行的人得有自己的连接。**起任务之前就问** —— 没有的话说清楚是哪个插件、去哪儿建,
    而不是起一个任务再让它失败。解析出来的连接不写回表单:下一个人点运行,用的是他自己的。
    """
    from app.domain.plugins.nodes import instances_for_node, parse_node_type, resolve_instance

    parsed = parse_node_type(node_type)
    if parsed is None:
        return
    package_id, tool_name = parsed
    #: 表单上选的连接**只在是他自己的时候**才算数。共享画板上那一格存着别人选的连接 id —— 那不是
    #: 「他选错了」,是「他没选」:按他自己的连接解析(只有一条就用它),而不是报「选的连接不可用」。
    chosen = str(config.get("instance_id") or "")
    mine = {one["id"] for one in instances_for_node(db, node_type, actor_id)}
    config["instance_id"] = resolve_instance(db, package_id, tool_name, chosen if chosen in mine else "", actor_id)


def _run_in_job(job_id: str, node_type: str, meta: dict[str, Any], scope: BoardScope, config: dict[str, Any],
                label: str) -> None:
    """任务线程里跑节点。父任务(current_parent_job_id)已经由 dispatch_job 设好。

    **先拿连接预算,再开会话**,和工作流引擎跑一个节点完全一样(见 engine.NODE_CONNECTIONS):
    节点里的等待(wait_for_job(release=db))会把预算交还再拿回来 —— 没先拿的话那一还就多出一份。
    """
    from app.core.db import SessionLocal
    from app.db.models import Job
    from app.domain.jobs import run_job_inline
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.engine import NODE_CONNECTIONS
    from app.domain.workflows.executors import get_executor

    def body() -> dict[str, Any]:
        handler = get_executor(node_type)
        if handler is None:
            raise WorkflowDomainError("wfErr_noExecutor", params={"type": node_type})
        with NODE_CONNECTIONS, SessionLocal() as node_db:
            output = handler(node_db, scope, dict(config))
            node_db.commit()
        return {"outputs": board_outputs(meta, output if isinstance(output, dict) else {"output": output})}

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            run_job_inline(db, job, body, running="jobMsg_boardRunRunning", done="jobMsg_boardRunDone")
        except Exception:  # noqa: BLE001 — 失败已经由 run_job_inline 落到任务上(回执随之送到那一格)
            logger.info("board_run %s (%s) failed", job_id, label, exc_info=True)


__all__ = [
    "BoardScope",
    "bindable_kinds",
    "binding_sink",
    "board_outputs",
    "check_bindings",
    "prepare_node_run",
    "resolve_bindings",
    "run_node_on_board",
]
