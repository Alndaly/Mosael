"""插件工具与 ComfyUI 工作台(ADR 0042)的 comfy_* 工具。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from typing import Any

from app.agent_tools.registry import (
    confirmation_reply,
    default_workspace_id,
    open_card,
    REQUESTED_BY,
    SESSION_ID,
    tool,
    use_case,
)
from app.domain.agent import plugin_lookup
from app.domain.workbench import agent as workbench_agent

# ---------- 这一轮工具表里没有的插件工具(ADR 0044 修订 2026-10-08,见 domain/agent/plugin_lookup) ----------
#
# 每一轮只发用得上的插件工具的完整定义(工作台里画布上那张工作流、这段对话调过的、点过名的;通用插件工具只发调过的)。别的经这两个:
# 找 / 看完整说明和全部入参 / 看某个下拉的可选值,和调一次。只在这一处这一轮发的那几份里找(工作台里是 ComfyUI 的,别处是通用插件的)。
# 这一轮一个没发的都没有时,这两个也不发(tool_manifest.ON_DEMAND_TOOLS)。


@tool(effect="reads")
def plugin_tools(query: str = "", tool: str = "", input: str = "") -> dict[str, Any]:  # noqa: A002
    """Read-only: plugin tools not in your list this turn. No `tool`: find them by `query` words. With `tool` (its
    name, or a saved workflow's path): its full description and inputs (`query` filters them). With `input` too: that
    input's options (`query` filters them)."""

    return use_case(plugin_lookup.lookup, query, tool, input, SESSION_ID.get())


@tool(effect="confirms")
def run_plugin_tool(tool: str, arguments: dict[str, Any] | None = None, workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: call a plugin tool not in your list this turn (`tool` as in plugin_tools; `arguments`:
    its inputs). Same card and result as calling it directly."""

    name = use_case(plugin_lookup.resolve_name, tool, SESSION_ID.get())
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "run_plugin_tool",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"tool": name, "arguments": dict(arguments or {})},
        },
    )
    return confirmation_reply(confirmation)


# ---------- ComfyUI 工作台里的智能体(ADR 0042:读和诊断、改和新建、补全和试跑) ----------
#
# 碰画布的(comfy_canvas_read / comfy_locate / comfy_check / comfy_canvas_edit / comfy_canvas_new / comfy_canvas_run)经桌面版主进程
# 交给那个连接开着的工作台;工作台没开着就说「先在工作台里打开这台 ComfyUI」。别的(模板、节点类型、节点包、模型库)只问那个连接的
# 插件,工作台开没开都能用。
# 改当前这张(comfy_canvas_edit)开确认卡、点「应用」才改;新标签页(comfy_canvas_new)不动开着的、不开卡;都不存盘。
# 第三步(补全和试跑,拍板 4、5):下载模型、装节点包、跑画布上这张——**都开确认卡**,卡上写清多大、哪台机器、装的是哪一版、
# 会不会重启;装节点包要等装完才重启(见 domain/workbench/agent)。
# `instance_id` 是 ComfyUI 连接的 id(工作台「助手」的页面上下文里有);调用的人只接了一台时可以不给。见 domain/workbench/agent。


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_canvas_read(instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Read-only summary of the ComfyUI workbench canvas (unsaved edits included): per layer (root graph, each
    subgraph) the nodes with ref, type, position, size, widget values and inputs (`in`: "<ref>.<output>"), spatial groups
    (`groups`: g1/g2 with title, position and size), plus selection, modified flag
    and missing node types. Refs: "12" at top level, "12:5" inside the subgraph of node 12; mention nodes as #12 / #12:5
    (the user can click them). Needs the workbench open."""

    return use_case(workbench_agent.canvas, workspace_id or default_workspace_id(), instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_locate(node: str, subgraph: str = "", instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Select and center a node on the workbench canvas, opening its subgraph first. `node`: a ref like "12"
    or "12:5". Changes nothing."""

    return use_case(workbench_agent.locate, workspace_id or default_workspace_id(), node, subgraph, instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_check(instance_id: str = "", job_id: str = "", last_error: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Read-only diagnosis of the workbench canvas: findings per node (ref, severity, kind, cause, fix) —
    missing nodes / models, mistyped or unconnected inputs, values outside a dropdown or range, size multiples, base
    model mismatches. A `missing_model` finding also carries `model` {name, folder, url?, sha256?, hash_type?,
    elsewhere?} — the file the workflow wants (and `elsewhere` when a same-named file sits in another subfolder), so you
    don't have to parse the prose `fix`. Pass the last run's `job_id` (page context) or `last_error` to map that error
    onto nodes."""

    return use_case(workbench_agent.check, workspace_id or default_workspace_id(), instance_id, job_id, last_error)


@tool(effect="confirms", needs="workflow_library", kit="comfyui")
def comfy_canvas_edit(ops: list[dict[str, Any]], instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: change the workflow open on the workbench canvas. One batch, all or nothing, one Ctrl+Z;
    the user sees the change list and clicks Apply. Refused up front if any op fails validation or the batch adds errors
    (comfy_check runs before and after; the result says what got fixed). Never saves. Ops — nodes as in comfy_canvas_read
    ("12"; "12:5" edits the subgraph definition, i.e. every use), new nodes by temporary id:
    add_node {id:"$a",type,widgets?,title?,near?,graph?} | remove_node {node} |
    connect {from:"<node>.<output>"|"@in.<name>", to:"<node>.<input>"|"@out.<name>"} | disconnect {to} |
    set_widget {node,widget,value} | set_title {node,title} | set_position {node,x,y} | bypass|mute {node,on?} |
    add_group {title,x,y,width,height,color?,graph?} | set_group {group,title?,x?,y?,width?,height?,color?,graph?} |
    remove_group {group,graph?} |
    add_subgraph_input|add_subgraph_output {graph,name,type} | remove_subgraph_io {graph,name,side?} |
    promote_widget|unpromote_widget {node,widget} | to_subgraph {nodes,name?} | unpack_subgraph {node} (these two last).
    graph = a subgraph node path ("12") or subgraph id."""
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "comfy_canvas_edit",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"ops": ops, "instance_id": instance_id},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="writes", needs="workflow_library", kit="comfyui")
def comfy_canvas_new(template: str = "", pack: str = "", ops: list[dict[str, Any]] | None = None, name: str = "", path: str = "",
                     instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Open a workflow in a NEW workbench tab; the open ones stay untouched, nothing is saved (the user saves).
    `template` (+`pack`): an official template adapted to this machine (prefer this); `ops` (comfy_canvas_edit ops, root
    graph): tweak the template or build from blank; `path`: a saved workflow instead. `name`: the tab name. Returns the tab,
    the template's missing models with sizes, and a check."""

    return use_case(workbench_agent.open_new, workspace_id or default_workspace_id(), template, pack, path, name, ops or [],
                     instance_id, opened_by=SESSION_ID.get())


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_templates(query: str = "", task: str = "", model: str = "", limit: int = 6, instance_id: str = "") -> dict[str, Any]:
    """Read-only: find official ComfyUI templates by `task`, `model` or `query`; prefer one over building
    from scratch. Each lists its models and whether this machine has them (or in another subfolder / precision), total
    `size` in bytes and the minimum ComfyUI version. Tell the user sizes before any download."""

    return use_case(workbench_agent.templates, query, task, model, limit, instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_template(name: str, pack: str = "", instance_id: str = "") -> dict[str, Any]:
    """Read-only: one template adapted to this machine — model status, the `changes` made (another subfolder
    / precision), what stays missing (URL, size), missing node types and a graph summary. Never invents files. `pack`:
    for node-pack templates."""

    return use_case(workbench_agent.template, name, pack, instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_node_types(query: str = "", classes: list[str] | None = None, limit: int = 10, instance_id: str = "") -> dict[str, Any]:
    """Read-only: ComfyUI node types — search with `query` or look up exact `classes`; inputs (type,
    required, options, default, range), outputs and pack."""

    return use_case(workbench_agent.node_types, query, classes or [], limit, instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_node_packs(instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Read-only: installed custom node packs (id, version, enabled, source, node types); with the
    workbench open, also which pack each canvas node comes from."""

    return use_case(workbench_agent.node_packs, workspace_id or default_workspace_id(), instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_node_pack_search(query: str = "", node_types: list[str] | None = None, instance_id: str = "") -> dict[str, Any]:
    """Read-only: find node packs by `query` or missing `node_types` (Manager mappings, then the
    Comfy Registry), ranked, installed ones marked. Check one with comfy_node_pack_info before recommending it."""

    return use_case(workbench_agent.node_pack_search, query, node_types or [], instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_node_pack_info(pack_id: str, instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Read-only: analyse a node pack before installing — registry status of the newest version
    (Flagged / Banned / deprecated: say so, don't recommend it; `install_version` is the latest normal one), publisher,
    license, downloads, stars, dependency risk (high if it touches torch), fit with this machine, the installed version
    and changelog, and which missing nodes it provides. Tell the user the `advice`."""

    return use_case(workbench_agent.node_pack_info, workspace_id or default_workspace_id(), pack_id, instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_model_search(filename: str, folder: str = "", hash: str = "", hash_type: str = "",  # noqa: A002
                       instance_id: str = "") -> dict[str, Any]:
    """Read-only: find download links for a model the workflow is missing, by `filename` (+ `folder`, and the `hash` the
    workflow declares with its `hash_type`). Returns `candidates` (source, filename, url, page, size, base_model, and
    `confidence`: only "confirmed" — the SHA256 matched — may be downloaded, `direct` is true then), the sites that
    failed, and the `hash` state. Never downloads."""

    return use_case(workbench_agent.model_search, filename, folder, hash, hash_type, instance_id)


@tool(effect="reads", needs="workflow_library", kit="comfyui")
def comfy_model_resolve(url: str, instance_id: str = "") -> dict[str, Any]:
    """Read-only: what a link points at — filename, size, suggested `folder`, source, title, triggers,
    whether that file is already on the machine (`exists`), and whether the download would use that site's token.
    Call it before comfy_model_download when the URL came from the user or a template."""

    return use_case(workbench_agent.model_resolve, url, instance_id)


@tool(effect="confirms", needs="workflow_library", kit="comfyui")
def comfy_model_download(url: str, folder: str, filename: str, sha256: str = "", instance_id: str = "",
                         workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: download a model onto that ComfyUI's disk. The card says which file, which folder, how big
    and on which machine — say the size before asking. Refused up front when the link doesn't resolve to `filename`,
    when the file is already there, or when `sha256` isn't 64 hex characters. The download runs in the background: the
    approved card's result carries the `job_id` — poll it with get_job; the catalog refreshes when it ends."""
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "comfy_model_download",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"instance_id": instance_id, "url": url, "folder": folder, "filename": filename, "sha256": sha256},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms", needs="workflow_library", kit="comfyui")
def comfy_node_pack_install(pack_id: str, version: str = "", instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: install ONE custom node pack from the Comfy Registry and restart that ComfyUI.
    `pack_id` is the registry id (comfy_node_pack_search / comfy_node_pack_info give it); git URLs are refused. Only a
    version that is active and not deprecated is installed — Banned packs and packs with no normal version are refused,
    and so are packs already installed at that version or disabled in ComfyUI. The card writes the version, publisher,
    dependency risk (torch) and fit with this machine; restarting interrupts running jobs. Waits for the install, then
    restarts, then reads the catalog back — the result says the version now installed."""
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "comfy_node_pack_install",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"instance_id": instance_id, "pack_id": pack_id, "version": version},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms", needs="workflow_library", kit="comfyui")
def comfy_canvas_run(instance_id: str = "", workspace_id: str = "", node_id: str = "") -> dict[str, Any]:
    """Confirmation required: run the workflow open on the ComfyUI workbench canvas (unsaved edits included) — the
    trial run behind "run it and read the errors". The workflow must have been saved at least once (ComfyUI's Ctrl+S);
    a brand-new tab is refused. Pass `node_id` (as shown by comfy_canvas_read) to execute only that output node and
    its upstream using ComfyUI partial execution; omit it to run the whole canvas. The approved card's result carries
    the `job_id`: poll it with get_job, outputs become assets, and on failure pass that job_id to comfy_check to map
    the error onto nodes."""
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "comfy_canvas_run",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"instance_id": instance_id, "node_id": node_id},
        },
    )
    return confirmation_reply(confirmation)
