"""工作流与画板:读、建、改、跑、看运行。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from mosael_formats.i18n import pick_text

from pydantic import Field
from typing import Annotated
from typing import Any

from app.agent_tools.registry import confirmation_reply, default_workspace_id, open_card, REQUESTED_BY, tool, use_case
from app.api.schemas import BoardOut, BoardProducerOut, BoardSummaryOut, WorkflowNodeTypeOut, WorkflowOut
from app.core.i18n import get_current_locale
from app.domain.boards import use_cases as boards_use_cases
from app.domain.job_center import use_cases as job_center_use_cases
from app.domain.workflows import use_cases as workflows_use_cases
from app.domain.workflows.run_progress import run_progress
from app.domain.workflows.templates.catalog import TEMPLATE_CATALOG

WORKFLOW_GRAPH_OP_KINDS = frozenset(
    {
        "add_node",
        "connect",
        "connect_data",
        "set_node_config",
        "set_node_name",
        "remove_node",
        "remove_edge",
    }
)


def looks_like_workflow_graph_ops(operations: list[dict[str, Any]] | None) -> bool:
    if not isinstance(operations, list):
        return False
    return any(
        isinstance(operation, dict) and operation.get("kind") in WORKFLOW_GRAPH_OP_KINDS
        for operation in operations
    )


@tool(effect="reads")
def list_workflows(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: list VISUAL WORKFLOWS in a workspace.

    Returns workflow id, name, description, and node count. Use this to find a
    workflow_id before get_workflow/edit_workflow/run_workflow. Do NOT use for
    video projects or timeline sequence IDs — use list_projects/inspect_sequence.
    """

    workflows = use_case(workflows_use_cases.list_workflows, workspace_id or default_workspace_id(), out=WorkflowOut)
    return [
        {
            "id": workflow["id"],
            "name": workflow["name"],
            "description": workflow["description"],
            "nodes": len((workflow.get("graph") or {}).get("nodes", [])),
        }
        for workflow in workflows
    ]


@tool(effect="reads")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Read-only: inspect one VISUAL WORKFLOW graph in full.

    Returns nodes, edges, configs, and workflow metadata. Use before edit_workflow
    or update_workflow so you preserve existing nodes/edges and know exact
    node_id values. Do NOT use for video timelines — use inspect_sequence.
    """

    return use_case(workflows_use_cases.readable, workflow_id, out=WorkflowOut)


@tool(effect="reads", kit="canvas")
def list_workflow_node_types(node_type: str = "") -> list[dict[str, Any]] | dict[str, Any]:
    """Read-only: list allowed workflow node types, or inspect one type in full.

    With no node_type, returns a compact catalog (type, label, category, config field
    names and outputs). Pass one catalog type back as node_type to get its complete
    config schema and output metadata before creating/configuring that node. Reference
    upstream outputs downstream as {{node_id.output}}.
    Do NOT use for video timeline tracks/clips or media asset tags.
    """

    rows = use_case(workflows_use_cases.node_types, get_current_locale(), out=WorkflowNodeTypeOut)
    wanted = node_type.strip()
    if wanted:
        match = next((row for row in rows if row.get("type") == wanted), None)
        if match is None:
            known = ", ".join(str(row.get("type") or "") for row in rows[:20])
            raise ValueError(f"Unknown workflow node type {wanted!r}. Known types: {known}")
        return match
    return [
        {
            "type": row.get("type", ""),
            "label": row.get("label", ""),
            "category": row.get("category", ""),
            "config_fields": list((row.get("config") or {}).keys()),
            "outputs": row.get("outputs") or [],
            "plugin_name": row.get("plugin_name", ""),
            "tool_name": row.get("tool_name", ""),
        }
        for row in rows
    ]


@tool(effect="confirms")
def create_workflow(
    name: str, graph: dict[str, Any] | None = None, description: str = "", workspace_id: str = "", template_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: create a NEW visual workflow.

    Use when the user wants a new workflow canvas/automation, not when editing an
    existing workflow. For an existing workflow use edit_workflow for node/edge
    changes or update_workflow only for rename/full replacement. graph =
    {"nodes": [{id,type,name,position,config}], "edges": [{id,source,target}]};
    omit graph for a bare start-node workflow. Check list_workflow_node_types first.
    template_id (from list_workflow_templates) builds it from an official template instead — the same graph the
    template library adds, with models picked from the user's settings; then set start params with run_workflow.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "create_workflow",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"name": name, "description": description, "graph": graph,
                        **({"template_id": template_id} if template_id else {})},
        },
    )
    return confirmation_reply(confirmation)


#: `edit_workflow` 的 operations 契约。**必须写进 schema,不能只写在 docstring 里**:
#: 模型见过的 docstring 是有限的,而工具参数表是结构化的、每条都会带上。把形状漏在注释里,
#: 就会出现"每条 operation 少了 kind"这种请求 —— 服务端只能回一句 `Unsupported workflow op: None`。
#: 只写"每条必须有 kind"这一句就够了 —— 每个字段的细节在 docstring 里,而**工具定义每轮都重发**,
#: 塞满就要挤占对话空间(tests/test_tool_definitions_budget.py 按每一处盯着)。
#: 这里只放**最小提示**:工具定义每轮都重发,长一句就挤占对话空间(tests/test_tool_definitions_budget.py 按每一处盯着)。
#: 完整的 kind 列表在 docstring 里;写错了会拿到一条点名的报错(见 confirmable/automation 的 validate)。
_WORKFLOW_OPS_HELP = "`kind` is required on every operation."


@tool(effect="confirms", kit="canvas")
def edit_workflow(
    workflow_id: str,
    operations: Annotated[list[dict[str, Any]], Field(description=_WORKFLOW_OPS_HELP)],
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: edit an EXISTING VISUAL WORKFLOW with granular graph ops.

    Use this for workflow canvas nodes/edges/configs: add_node, connect,
    connect_data, set_node_config, set_node_name, remove_node, remove_edge.
    Prefer this over update_workflow for almost every workflow edit. The server
    applies your ops onto the current graph, so you do not regenerate or replace
    the whole graph. Ops apply in order, so add_node then connect in one call
    works. Check get_workflow first for exact node_id values and
    list_workflow_node_types for node types/config fields. Do NOT use for video
    timeline clips/tracks/sequences — use edit_timeline. remove_node may delete
    the start node too; a workflow with no start node is saved as a draft but
    cannot run until a start node is added again.

    operations is a list of:
      {"kind":"add_node","type":"llm","name":"改写","node_id":"llm_1","config":{"prompt":"..."}}
          (node_id/name/position/config optional; server auto-ids and lays out)
      {"kind":"connect","source":"start","target":"llm_1","source_handle":"true|false (condition only)"}
      {"kind":"connect_data","source":"http_1","source_output":"text","target":"llm_1","target_input":"prompt"}
      {"kind":"set_node_config","node_id":"llm_1","config":{"prompt":"新提示词"}}   (merges)
      {"kind":"set_node_name","node_id":"llm_1","name":"新名字"}
      {"kind":"remove_node","node_id":"llm_1"}                                     (drops its edges too)
      {"kind":"remove_edge","edge_id":"e-start-llm_1"}
    Strings may use {{node_id.output}}; code fields read the node's `input` instead.

    形状(默认画一条直线是最常见的浪费):
      并排 —— 同一个 source 连出多条边就是并发执行,总时长按最慢的那支算:
        {"kind":"connect","source":"start","target":"img_1"}
        {"kind":"connect","source":"start","target":"img_2"}
      subgraph —— 把一段复杂但只用一次的流程折成一个节点,config.body 里嵌一整张子画布,
      内部用 {{input.名}} 取外层喂进来的值:
        {"kind":"add_node","type":"subgraph","node_id":"sub_1","config":{
           "inputs":{"稿子":"{{llm_1.text}}"},
           "body":{"nodes":[{"id":"t_1","type":"template","config":{"template":"{{input.稿子}}"}}],"edges":[]},
           "output":"{{t_1.text}}"}}
      loop_foreach / loop_while —— 体内用 {{loop.item}} / {{loop.index}} 取当前项和序号(loop_while 只有
      {{loop.index}}),{{loop.previous}} 取上一轮的输出(第一轮是 previous_initial;用它时循环只能一项一项跑),
      {{input.名}} 取 inputs 传进来的值;容器自己的 output / condition 引用体内节点的输出。
      (节点说明是给人看的,不写这种写法;体内看得见什么以 list_workflow_node_types 的 body_scope 为准。)
      call_workflow —— 一段会被别处复用的流程,抽成独立工作流再调它(复制粘贴的两份迟早不一样):
        {"kind":"add_node","type":"call_workflow","node_id":"call_1",
         "config":{"workflow_id":"<另一张图的 id>","inputs":{"标题":"{{start.text}}"}}}
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "edit_workflow",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"workflow_id": workflow_id, "operations": operations},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms", kit="canvas")
def update_workflow(workflow_id: str, graph: dict[str, Any] | None = None, name: str = "", description: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: rename a workflow or replace its ENTIRE graph.

    Use this only for metadata rename/description changes, or when the user
    explicitly wants a wholesale graph replacement. This is NOT for routine
    add/remove/configure node edits; use edit_workflow for those. When passing
    graph, read the current one with get_workflow first because update_workflow
    replaces the graph; it does not merge and can drop omitted nodes/edges.
    """
    payload: dict[str, Any] = {"workflow_id": workflow_id}
    if graph is not None:
        payload["graph"] = graph
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "update_workflow",
            "requested_by": REQUESTED_BY.get(),
            "payload": payload,
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="reads")
def list_boards(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: list CREATIVE BOARDS (infinite canvases) in a workspace.

    A board is a free-form canvas of notes, images, videos, audio and group
    frames that the user brainstorms on — NOT a visual workflow and NOT a video
    timeline. Use this to find a board_id before get_board/edit_board.
    """

    # 清单给的是**摘要**(board_summary:格子数 + 缩略图那一份),不带整份 canvas —— 按摘要的形状校验。
    # 此前拿详情的 BoardOut 去校验,工作区里只要有一张板就报「canvas Field required」(用户会话里连报三次,
    # 模型以为是数据坏了);空工作区一行都没有,所以冒烟测试一直是绿的(见 tests/test_mcp_read_tools_with_data)。
    boards = use_case(boards_use_cases.list_all, workspace_id or default_workspace_id(), out=BoardSummaryOut)
    return [{"id": b["id"], "name": b["name"], "items": b["item_count"]} for b in boards]


@tool(effect="reads", kit="canvas")
def get_board(board_id: str, workspace_id: str = "") -> dict[str, Any]:
    """Read-only: inspect one CREATIVE BOARD canvas in full.

    Returns every item (id, kind, title, x, y, width, height, text, color, asset_id)
    and every edge. `title` is the item's user-given name (absent = unnamed; the
    canvas then shows the kind, e.g. "Image") — use it to tell apart items of the
    same kind and to refer to them. Call this before edit_board so you know the
    exact item_id values and where things already sit — the user has arranged
    them by hand. An item's form.abilities holds the last-used settings of each of
    its abilities ({producer: {config, bindings}}); run (status, job_id, error,
    ability) says what is running on it — `ability` names the ability when the run
    is one. An empty slot running a plugin generator carries form.producer (that
    generator), form.config and form.bindings; a 3D scene item (kind "scene")
    carries form.producer "scene_render" and form.config (its render settings).
    A TIMELINE item (kind "sequence") is a real Mosael timeline: its sequence_id works
    with inspect_sequence (see its clips) and edit_timeline (split, move, trim…); it
    carries form.producer "sequence_export" and form.config (its export settings).
    """

    return use_case(boards_use_cases.read, board_id, workspace_id or default_workspace_id(), out=BoardOut)


@tool(effect="confirms", kit="canvas")
def edit_board(board_id: str, operations: list[dict[str, Any]], workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: edit an EXISTING CREATIVE BOARD with granular canvas ops.

    Use for anything on the board canvas: adding notes/image/video/audio slots,
    rewriting a note, recolouring, moving or resizing, connecting items, deleting.
    The server applies your ops onto the CURRENT canvas, so you never rewrite the
    whole board — rewriting it wipes the positions the user arranged by hand.
    Call get_board first for exact item_id values. Do NOT use for visual workflows
    (edit_workflow) or video timelines (edit_timeline).

    An image/video/audio item with no asset_id is an EMPTY SLOT: the user writes a
    prompt on it and generates. Adding empty slots is how you set up work for them.

    There are NO separate tool items. Tools that turn content into new content are
    ABILITIES of the content item itself (audio/video: transcribe, separate vocals,
    denoise; video: to GIF; note/document: translate; plugin tools on the kinds
    their content input takes — see list_board_producers, role "ability"). The
    item's own content is the tool's input (the field named in host_fields — do not
    set it). To prepare one, set_form on the HOST item with that ability's
    `producer`: `config` is its other settings, `bindings` feeds its other inputs
    from items connected INTO the host ({field: [{"from": item_id}]}; connect them in
    the same batch; the upstream kind must be one the field's board_sources lists).
    Run it with run_board_item(item_id=host, producer=...); outputs land as new
    items to the host's right. A plugin GENERATOR that consumes no board content
    (role "slot") is set as an empty slot's own producer instead: add_item an empty
    image/video/audio slot with `producer`/`config`, or set_form it on one.

    A 3D SCENE ITEM (type "scene") renders itself: there is no separate render tool
    item. Its producer is "scene_render"; set its `config` (shot_id — a shot of that
    scene, may stay empty when the scene has one shot; render — stills / video / both)
    with set_form, then run_board_item on the scene item. The first/last frame and
    the camera-move video land as new items to its right.

    A TIMELINE ITEM (type "sequence") strings clips into one video right on the board.
    add_item it WITHOUT sequence_id to start a new timeline (created on approval, in
    the board's own project, named after the board), or with the sequence_id of an
    existing timeline of this workspace. CONNECTING a video / image / audio item that
    has an asset INTO it appends that asset to the end of the timeline (video and
    images to the main video track, audio to the audio track) — the same as the user
    drawing that line; empty slots add nothing, and removing the line does not remove
    the clip. Fine edits (split, reorder, trim) are edit_timeline on its sequence_id.
    To export it, set_form its `config` (resolution original/1080p/720p/480p, quality
    high/standard/compact, ai_label yes/no — all optional) and run_board_item on it;
    the finished video lands as a new item to its right.

    operations is a list of:
      {"kind":"add_item","type":"note","item_id":"n1","x":80,"y":120,"text":"开场白","color":"yellow"}
          (item_id/x/y/width/height/title optional — the server auto-ids and lays out to the right)
          type is one of note / image / video / audio / frame / scene / document / entity / sequence
      {"kind":"add_item","type":"image","asset_id":"<asset id>"}
          (places an existing asset; it must be in this workspace and match the item type:
           image → image asset, video → video asset, audio → audio asset)
      {"kind":"add_item","type":"scene","scene_id":"<list_scenes id>"}
          (a 3D scene item REQUIRES scene_id — a scene of this workspace; without it the op is rejected)
      {"kind":"add_item","type":"entity","entity_id":"<list_entities id>"}
          (an ASSET item — a character / location / prop from the asset library; it REQUIRES entity_id.
           connect it into an image/video slot and that generation uses it exactly like an @mention:
           its prompt descriptor is appended and its reference images are attached)
      {"kind":"add_item","type":"sequence","item_id":"t1"}
          (a NEW timeline, created when the user approves; add "sequence_id":"<id>" to show an existing one)
      {"kind":"connect","source":"v1","target":"t1"}
          (into a timeline item: appends v1's asset to the end of that timeline)
      {"kind":"add_item","type":"frame","title":"第一幕"}
          (a frame is named by title; it has no text)
      {"kind":"add_item","type":"document","note_id":"<read_note id>","note_revision":1}
          (pins a workspace note revision; connect to writing/image/video/audio nodes to use its full text)
      {"kind":"add_item","type":"document","asset_id":"<list_assets id, kind document>"}
          (an imported PDF / Word / PowerPoint / Excel file as a read-only source: connected items get its
           parsed full text; use either note_id or asset_id, not both)
      {"kind":"set_title","item_id":"i1","title":"主视觉"}
          (name/rename any item, max 120 chars; "" clears the name)
      {"kind":"set_text","item_id":"n1","text":"新内容"}
      {"kind":"set_color","item_id":"n1","color":"green"}      (notes: yellow/blue/green/pink/purple/gray)
      {"kind":"move_item","item_id":"n1","x":400,"y":200}
      {"kind":"resize_item","item_id":"n1","width":320,"height":200}
      {"kind":"connect","source":"n1","target":"i1"}
          (a line from A to B; the downstream node picks up A's output as its reference)
      {"kind":"remove_item","item_id":"n1"}                     (its edges go too)
      {"kind":"remove_edge","edge_id":"e-n1-i1"}
      {"kind":"set_form","item_id":"n1","producer":"node:translate","config":{"target_lang":"en"}}
          (the settings of note n1's "translate" ability — n1's own text is what gets translated;
           config merges key by key, null removes a key; bindings replace per field, [] unbinds)
      {"kind":"add_item","type":"video","item_id":"v2","producer":"node:plugin.<package>.<tool>",
       "config":{"prompt":"…"}}
          (an empty slot filled by a plugin generator — role "slot" in list_board_producers)
      {"kind":"set_form","item_id":"s1","config":{"shot_id":"<shot id>","render":"both"}}
          (a 3D scene item's render settings; scene_render takes no bindings)
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "edit_board",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"board_id": board_id, "operations": operations},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="reads", kit="canvas")
def list_board_producers(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: list what content items on a creative board can DO — abilities and slot generators.

    A board holds only CONTENT TRANSFORMS (video to GIF, transcribe, translate, separate
    vocals, denoise, a ComfyUI workflow…) or generators that make new assets. Flow control
    and data plumbing (workflows, HTTP, templates, JSON, note search) are not board tools.

    Each entry: a producer id (use it as `producer` in edit_board set_form/add_item and
    run_board_item), label, `role`, `hosts`, `board_description`, `effects` ("none" runs
    directly; "paid"/"external" asks first) and `config` — fields a creator fills (type,
    required, options, description; mappings, raw JSON and code fields are not on the board).
      role "ability": the host item's own content fills `host_fields[kind]` — never set it.
        Store settings with set_form on the host (with `producer`) and run it with
        run_board_item(item_id=host, producer=id); outputs land to its right.
      role "slot": consumes no board content; fills an EMPTY slot of a kind in `hosts`.
    `board_sources` lists the kinds a field takes from connected items (via `bindings`); an
    empty list means fill it in `config`. Plugin tools appear only for connected plugins;
    built-in generate/write/speak slots are not listed. Also listed: "scene_render" (scene
    items render themselves) and "sequence_export" (timeline items export themselves).
    """

    # 同一个出口形状(和界面从 /boards/producers 拿到的逐字一样):经 HTTP 时那一层会按它过滤。
    listed = use_case(
        boards_use_cases.producers_for, workspace_id or default_workspace_id(), get_current_locale(), out=BoardProducerOut
    )
    return [one for one in listed if one.get("runs_from_draft")]


@tool(effect="confirms", kit="canvas")
def run_board_item(board_id: str, item_id: str, producer: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Run an ABILITY of a content item on a creative board (or its slot generator / 3D render), as if the user pressed it.

    With `producer` (an id from list_board_producers, role "ability"): runs that ability
    on the item — the item's own content is the input, its settings are the ones stored
    on the item (set them first with edit_board set_form, same producer). Without it:
    runs the item's own producer when that is runnable from its saved form — a plugin
    generator on an empty slot, or a 3D scene item's render (form.config shot_id /
    render). Uses the user's own plugin connection. A read-only tool (effects "none")
    runs directly; one that costs money or acts outside the app needs the user's
    approval first. The result means the run has STARTED (it returns the job_id); it
    finishes in the background and its outputs land as new items to the right of the
    item, connected to it (a slot generator fills the slot itself) — get_job(job_id)
    says when, get_board shows them. Do NOT use for built-in generate/write/voice-over
    (the user starts those from their panel) or for visual workflows (run_workflow).
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "run_board_item",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"board_id": board_id, "item_id": item_id, **({"producer": producer} if producer else {})},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def run_workflow(
    workflow_id: str, params: dict[str, Any] | None = None, workspace_id: str = "",
    runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Confirmation required: execute an EXISTING visual workflow.

    Use after get_workflow when the user wants to run the workflow automation.
    params supplies start/input variables. This may spend AI/render budget, so it
    requires the user's approval; the run starts only if they approve. Do NOT use to edit the workflow graph (edit_workflow/update_workflow) or
    export a video timeline (render_sequence).
    runs (instead of params): several start-param sets, one run each, all started in parallel on one approval
    (e.g. one run per scene of an episode); returns job_ids. Follow each with get_workflow_run.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "run_workflow",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"workflow_id": workflow_id, "params": params or {}, **({"runs": runs} if runs else {})},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms", kit="canvas")
def continue_workflow_run(job_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Confirmation required: continue a failed, interrupted or cancelled workflow run from where it stopped.

    Steps that already finished are not redone (and not paid again). params overrides start params for the
    steps still to run. Check get_workflow_run first: can_continue says whether it applies.
    """

    #: 卡开在这次运行所在的工作区(读得到它才开:读不到的在这里就拒,不开一张注定失败的卡)。
    workspace_id = use_case(lambda db, user: job_center_use_cases.readable(db, user, job_id).workspace_id)
    confirmation = open_card(
        {
            "workspace_id": workspace_id,
            "tool": "continue_workflow_run",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"job_id": job_id, "params": params or {}},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="reads", kit="canvas")
def get_workflow_run(job_id: str) -> dict[str, Any]:
    """Read-only: how far one workflow run has got — status, progress, finished and remaining top-level steps,
    sub-task counts by kind:status (image / video / speech generations…), recent failure reasons, money spent,
    and can_continue. Use to watch long runs (call again later; do not poll in a tight loop)."""

    def progress(db, user) -> dict[str, Any]:
        job = job_center_use_cases.readable(db, user, job_id)
        if job.kind != "workflow":
            raise ValueError(f"{job_id} is a {job.kind} job, not a workflow run — use get_job")
        return run_progress(db, job)

    return use_case(progress)


@tool(effect="reads", kit="canvas")
def list_workflow_templates() -> list[dict[str, Any]]:
    """Read-only: the official workflow templates — id (pass to create_workflow template_id), name, what it does,
    its stages and what it needs (models, engines). E.g. series_setup builds a series' episodes, characters with
    voices and locations into the asset library; full_video_generation shoots one episode or scene from a topic."""
    locale = get_current_locale()
    return [
        {
            "id": str(template["id"]),
            "name": pick_text(template["name"], locale),
            "summary": pick_text(template["summary"], locale),
            "needs": [pick_text(one["text"], locale) + (" (optional)" if one["optional"] else "") for one in template["requires"]],
        }
        for template in TEMPLATE_CATALOG
    ]
