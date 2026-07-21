"""Mibu MCP server (stdio).

Minimal external-agent surface per plan §17: stable product semantics only —
summaries, never raw internal schemas. Talks to the local backend HTTP API so
domain rules and (future) permissions apply uniformly.

Run:  .venv/bin/python mcp_server.py            (from backend/)
Env:  MIBU_API   (default http://127.0.0.1:8800)
      MIBU_TOKEN (session token from login; required now that the API
                  enforces local authentication)
"""

from __future__ import annotations

import contextvars
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

#: Where the tool bodies call back to. Bound per context for the same reason the token is:
#: as a stdio MCP server the environment settles it, but in-process (the pi sidecar path) the
#: backend knows its own address and the default is only right by coincidence. It was baked in
#: at import time, so every tool 401'd or misrouted the moment the backend ran on any port
#: other than 8800 — a packaged build picking a free port, or two instances side by side.
_API_BASE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mibu_api_base", default=os.environ.get("MIBU_API", "http://127.0.0.1:8800")
)


def set_api_base(base: str) -> contextvars.Token:
    return _API_BASE.set(base)


def api_base() -> str:
    return _API_BASE.get()

# The token is a ContextVar rather than a module constant because this module has two callers.
# As a stdio MCP server it is one process per turn and the environment is enough; but the
# backend also imports it to serve the same tools to the pi sidecar, where a single process
# handles many users' turns concurrently and each needs its own credential. A global would leak
# one caller's token into another's request.
_API_TOKEN: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mibu_api_token", default=os.environ.get("MIBU_TOKEN", "")
)


def set_api_token(token: str):
    """Bind the token for the current context. Returns the reset token."""
    return _API_TOKEN.set(token)


def _auth_headers() -> dict[str, str]:
    token = _API_TOKEN.get()
    return {"Authorization": f"Bearer {token}"} if token else {}

mcp = FastMCP("mibu")


def _raise_with_detail(response: httpx.Response) -> None:
    """4xx/5xx 时把后端的 detail 带进异常文本。

    裸的 `422 Unprocessable Content` 对模型毫无用处——它无法自我纠正;
    detail(如「不能删除 start 节点」)才是它需要的反馈。"""
    if response.is_success:
        return
    detail = ""
    try:
        body = response.json()
        detail = str(body.get("detail", "")) if isinstance(body, dict) else ""
    except ValueError:
        detail = response.text[:300]
    message = f"{response.status_code} {response.reason_phrase}"
    if detail:
        message += f": {detail}"
    raise ValueError(message)


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    headers = _auth_headers()
    with httpx.Client(base_url=api_base(), timeout=15, headers=headers) as client:
        response = client.get(path, params=params)
        _raise_with_detail(response)
        return response.json()


def _post(path: str, payload: dict[str, Any]) -> Any:
    headers = _auth_headers()
    with httpx.Client(base_url=api_base(), timeout=30, headers=headers) as client:
        response = client.post(path, json=payload)
        _raise_with_detail(response)
        return response.json()


def _patch(path: str, payload: dict[str, Any]) -> Any:
    headers = _auth_headers()
    with httpx.Client(base_url=api_base(), timeout=30, headers=headers) as client:
        response = client.patch(path, json=payload)
        _raise_with_detail(response)
        return response.json()


def _default_workspace_id() -> str:
    workspaces = _get("/api/workspaces")
    if not workspaces:
        raise ValueError("No workspace available")
    return workspaces[0]["id"]


# 确认门控的工具集合:manifest(/api/agent/tools)据此给每个工具打 confirmation 标,
# 各 runtime(pi sidecar / MCP 客户端)统一从元数据生成阻塞或轮询逻辑,不再手写第二份。
CONFIRMATION_TOOLS = frozenset(
    {
        "edit_timeline",
        "render_sequence",
        "generate_image",
        "generate_video",
        "create_workflow",
        "edit_workflow",
        "update_workflow",
        "run_workflow",
    }
)

# 确认卡上显示的请求方。经 /api/agent/tools 间接调用时由调用方标注(如 "pi-agent"),
# 直连 MCP(Claude CLI 等)保持默认。
_REQUESTED_BY: contextvars.ContextVar[str] = contextvars.ContextVar("mibu_requested_by", default="mcp-agent")


def set_requested_by(name: str) -> contextvars.Token:
    return _REQUESTED_BY.set(name)


def _confirmation_reply(confirmation: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmation_id": confirmation["id"],
        "status": confirmation["status"],
        "permission": confirmation["permission"],
        "summary": confirmation["summary"],
        "message": "等待用户在 Mibu 中确认。用 get_confirmation 轮询结果；批准后 result 才会填充。",
    }


@mcp.tool()
def list_assets(workspace_id: str = "", kind: str = "", name_contains: str = "") -> list[dict[str, Any]]:
    """List media assets in a workspace (id, name, kind, source, duration).

    Filter with kind ("video"/"image"/"audio") and/or name_contains to batch-select.
    Leave workspace_id empty to use the first workspace.
    """
    if not workspace_id:
        workspaces = _get("/api/workspaces")
        if not workspaces:
            return []
        workspace_id = workspaces[0]["id"]
    params: dict[str, Any] = {"workspace_id": workspace_id}
    if kind:
        params["kind"] = kind
    if name_contains:
        params["name_contains"] = name_contains
    assets = _get("/api/assets", params)
    return [
        {
            "id": asset["id"],
            "name": asset["name"],
            "kind": asset["kind"],
            "source": asset["source"],
            "duration_seconds": asset.get("media_info", {}).get("duration"),
        }
        for asset in assets
    ]


@mcp.tool()
def inspect_sequence(sequence_id: str = "", project_id: str = "") -> dict[str, Any]:
    """Summarize a timeline: format, revision, duration, tracks, and clips.

    Provide sequence_id, or project_id to inspect its most recent sequence.
    """
    if not sequence_id:
        if not project_id:
            raise ValueError("Provide sequence_id or project_id")
        sequences = _get(f"/api/projects/{project_id}/sequences")
        if not sequences:
            raise ValueError("Project has no sequences")
        sequence_id = sequences[0]["id"]
    sequence = _get(f"/api/sequences/{sequence_id}")

    workspaces_assets = {
        asset["id"]: asset["name"]
        for asset in _get("/api/assets", {"workspace_id": sequence["workspace_id"]})
    }
    duration = 0.0
    tracks_summary = []
    for track in sequence.get("tracks", []):
        clips_summary = []
        for clip in track.get("clips", []):
            clip_duration = clip["src_out"] - clip["src_in"]
            duration = max(duration, clip["timeline_start"] + clip_duration)
            clips_summary.append(
                {
                    "clip_id": clip["id"],
                    "asset": workspaces_assets.get(clip["asset_id"], clip["asset_id"]),
                    "timeline_start": clip["timeline_start"],
                    "duration": round(clip_duration, 3),
                }
            )
        tracks_summary.append(
            {
                "name": track["name"],
                "kind": track["kind"],
                "clip_count": len(clips_summary),
                "clips": clips_summary,
            }
        )
    return {
        "sequence_id": sequence["id"],
        "name": sequence["name"],
        "format": f"{sequence['width']}x{sequence['height']} @ {sequence['fps']}fps",
        "revision": sequence["revision"],
        "duration_seconds": round(duration, 3),
        "tracks": tracks_summary,
    }


@mcp.tool()
def list_projects(workspace_id: str = "") -> list[dict[str, Any]]:
    """List projects in a workspace (id, name, active_sequence_id)."""
    if not workspace_id:
        workspaces = _get("/api/workspaces")
        if not workspaces:
            return []
        workspace_id = workspaces[0]["id"]
    projects = _get("/api/projects", {"workspace_id": workspace_id})
    return [
        {"id": project["id"], "name": project["name"], "active_sequence_id": project.get("active_sequence_id")}
        for project in projects
    ]


@mcp.tool()
def edit_timeline(sequence_id: str, operations: list[dict[str, Any]], workspace_id: str = "") -> dict[str, Any]:
    """Propose timeline edits (permission: edit). Requires user confirmation in Mibu.

    operations: list of {kind, ...args}. Supported kinds: insert_clip
    (track_id, asset_id, timeline_start, src_in, src_out), move_clip
    (clip_id, timeline_start), trim_clip (clip_id, timeline_start, src_in,
    src_out), delete_clip (clip_id), cut_clip_range (clip_id, src_start,
    src_end), add_track (track_kind), remove_track (track_id),
    set_clip_effects (clip_id, effects).
    Every applied edit is undoable by the user.
    """
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "edit_timeline",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"sequence_id": sequence_id, "operations": operations},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def render_sequence(sequence_id: str, workspace_id: str = "") -> dict[str, Any]:
    """Export a timeline to mp4 (permission: render-cost). Requires user confirmation.

    After approval the confirmation result carries the render job id.
    """
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "render_sequence",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"sequence_id": sequence_id},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def generate_image(prompt: str, model: str = "mock-image", provider: str = "mock", workspace_id: str = "") -> dict[str, Any]:
    """Generate an image asset (permission: ai-cost). Requires user confirmation.

    After approval the result carries job_id; the finished image lands in the
    media pool as a generated asset.
    """
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "generate_image",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"prompt": prompt, "provider": provider, "model": model, "parameters": {}},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def generate_video(prompt: str, model: str = "mock-video", provider: str = "mock", workspace_id: str = "") -> dict[str, Any]:
    """Generate a video asset (permission: ai-cost). Requires user confirmation."""
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "generate_video",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"prompt": prompt, "provider": provider, "model": model, "parameters": {}},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def analyze_asset(asset_id: str, question: str = "") -> dict[str, Any]:
    """Understand an image or video asset with a multimodal model (small ai-cost, runs directly).

    Videos are sampled into frames; ask about content, scenes, text on
    screen, mood, best moments for cutting, etc.
    """
    return _post(f"/api/assets/{asset_id}/analyze", {"question": question})


@mcp.tool()
def list_plugin_tools() -> list[dict[str, Any]]:
    """List tools contributed by enabled (and permission-granted) user plugins.

    Each entry has plugin_id, tool_name, description, and input_schema — call
    them with invoke_plugin_tool. Plugins are pure functions over their input
    (no timeline mutation, no network) so calls run directly.
    """
    return _get("/api/plugins/tools")


@mcp.tool()
def invoke_plugin_tool(plugin_id: str, tool_name: str, input: dict[str, Any]) -> dict[str, Any]:
    """Run a plugin tool (see list_plugin_tools) with a JSON input payload.

    Returns the invocation record: status succeeded/failed, output, error.
    """
    invocation = _post(f"/api/plugins/{plugin_id}/tools/{tool_name}/invoke", {"input": input})
    return {
        "status": invocation["status"],
        "output": invocation.get("output") or {},
        "error": invocation.get("error"),
    }


@mcp.tool()
def search_kb(query: str, workspace_id: str = "", dataset_id: str = "", limit: int = 6) -> list[dict[str, Any]]:
    """Search the knowledge base (scripts, briefs, notes, imported articles).

    Use this BEFORE writing copy, planning a cut, or answering questions about
    the user's project background — the KB holds their scripts, style guides
    and reference material. Returns per-chunk best-matching snippets with
    document_id and score; call read_kb_document for the full text. Chinese and
    English queries both work (trigram index). Do NOT use for media assets —
    that is list_assets/analyze_asset.

    The KB is organised into datasets. Pass dataset_id to search one dataset;
    leave it empty to search every dataset in the workspace (results merged and
    re-ranked by score). Leave workspace_id empty to use the first workspace.
    """
    if dataset_id:
        return _get(f"/api/kb/datasets/{dataset_id}/search", {"q": query, "limit": limit})

    ws = workspace_id or _default_workspace_id()
    datasets = _get("/api/kb/datasets", {"workspace_id": ws})
    hits: list[dict[str, Any]] = []
    for dataset in datasets:
        hits.extend(_get(f"/api/kb/datasets/{dataset['id']}/search", {"q": query, "limit": limit}))
    # Each dataset ranks independently; merge and keep the globally best `limit`.
    hits.sort(key=lambda hit: hit.get("score", 0.0), reverse=True)
    return hits[:limit]


@mcp.tool()
def read_kb_document(document_id: str) -> dict[str, Any]:
    """Read one knowledge-base document in full (title, markdown content, tags).

    Get document_id from search_kb results or the user. Prefer search_kb
    snippets when you only need a fact; read the full document when you must
    follow a script or style guide precisely.
    """
    doc = _get(f"/api/kb/documents/{document_id}")
    return {
        "document_id": doc["id"],
        "title": doc["title"],
        "source_type": doc["source_type"],
        "source_ref": doc["source_ref"],
        "tags": doc.get("tags", []),
        "content": doc.get("content") or "",
    }


@mcp.tool()
def create_kb_note(title: str, content: str, workspace_id: str = "", tags: list[str] | None = None) -> dict[str, Any]:
    """Save a note into the knowledge base (runs directly, no confirmation).

    Use to persist reusable creative output the user asks you to keep:
    finalized scripts, shot lists, title/description drafts, research digests.
    Do NOT dump raw chat replies — save polished, reusable material with a
    clear title.
    """
    ws = workspace_id or _default_workspace_id()
    doc = _post(
        "/api/kb/documents",
        {"workspace_id": ws, "title": title, "content": content, "source_type": "note", "tags": tags or []},
    )
    return {"document_id": doc["id"], "title": doc["title"]}


@mcp.tool()
def list_skills() -> list[dict[str, Any]]:
    """List available agent skills (reusable playbooks for common Mibu workflows).

    Each entry has id, name, description. When a task matches a skill, call
    load_skill(id) and follow its body strictly.
    """
    return _get("/api/agent/prompt-skills")


@mcp.tool()
def load_skill(skill_id: str) -> dict[str, Any]:
    """Load one skill's full playbook body (markdown). Follow it step by step."""
    return _get(f"/api/agent/prompt-skills/{skill_id}")


@mcp.tool()
def update_asset_tags(asset_id: str, tags: list[str]) -> dict[str, Any]:
    """Replace an asset's tag list (metadata only, reversible — runs directly).

    Read the asset's current tags via list_assets first if you want to merge
    instead of replace.
    """
    asset = _patch(f"/api/assets/{asset_id}", {"tags": tags})
    return {"asset_id": asset["id"], "name": asset["name"], "tags": asset.get("tags", [])}


@mcp.tool()
def web_search(query: str, count: int = 5) -> list[dict[str, Any]]:
    """Search the web for up-to-date info (read-only, runs directly). Returns up to `count`
    results as {title, url, snippet}. Follow up with fetch_url to read a promising page."""
    return _get("/api/websearch", {"q": query, "count": count}).get("results", [])


@mcp.tool()
def fetch_url(url: str) -> dict[str, Any]:
    """Fetch a public web page and return its readable text as {title, url, text} (read-only).
    Only http/https public pages; internal/localhost addresses are blocked."""
    return _get("/api/webfetch", {"url": url})


@mcp.tool()
def list_workflows(workspace_id: str = "") -> list[dict[str, Any]]:
    """List visual workflows (id, name, description, node count). Read-only, runs directly."""
    workflows = _get("/api/workflows", {"workspace_id": workspace_id or _default_workspace_id()})
    return [
        {
            "id": workflow["id"],
            "name": workflow["name"],
            "description": workflow["description"],
            "nodes": len((workflow.get("graph") or {}).get("nodes", [])),
        }
        for workflow in workflows
    ]


@mcp.tool()
def get_workflow(workflow_id: str) -> dict[str, Any]:
    """Read a workflow's full graph (nodes/edges/configs). Read-only, runs directly."""
    return _get(f"/api/workflows/{workflow_id}")


@mcp.tool()
def list_workflow_node_types() -> list[dict[str, Any]]:
    """Node type registry for building workflow graphs: config fields and output
    variables per type. Reference outputs downstream as {{node_id.output}}."""
    return _get("/api/workflows/node-types")


@mcp.tool()
def create_workflow(name: str, graph: dict[str, Any] | None = None, description: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Create a visual workflow (permission: edit). Requires user confirmation.

    graph = {"nodes": [{id,type,name,position,config}], "edges": [{id,source,target}]};
    omit graph for a bare start-node workflow. Check list_workflow_node_types first.
    """
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "create_workflow",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"name": name, "description": description, "graph": graph},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def edit_workflow(workflow_id: str, operations: list[dict[str, Any]], workspace_id: str = "") -> dict[str, Any]:
    """Edit a workflow with granular ops — PREFER THIS over update_workflow (permission: edit,
    requires user confirmation). You describe intent; the server applies it to the current graph,
    so you never regenerate the whole graph. Ops apply in order, so add_node then connect in one
    call works. Check list_workflow_node_types for available types and their config fields.

    operations is a list of:
      {"kind":"add_node","type":"llm","name":"改写","node_id":"llm_1","config":{"prompt":"..."}}
          (node_id/name/position/config optional; server auto-ids and lays out)
      {"kind":"connect","source":"start","target":"llm_1","source_handle":"true|false (condition only)"}
      {"kind":"connect_data","source":"kb_1","source_output":"text","target":"llm_1","target_input":"prompt"}
      {"kind":"set_node_config","node_id":"llm_1","config":{"prompt":"新提示词"}}   (merges)
      {"kind":"set_node_name","node_id":"llm_1","name":"新名字"}
      {"kind":"remove_node","node_id":"llm_1"}                                     (drops its edges too)
      {"kind":"remove_edge","edge_id":"e-start-llm_1"}
    Config string values may reference upstream outputs as {{node_id.output}}.
    """
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "edit_workflow",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"workflow_id": workflow_id, "operations": operations},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def update_workflow(workflow_id: str, graph: dict[str, Any] | None = None, name: str = "", description: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Replace a workflow's ENTIRE graph and/or rename it (permission: edit, requires confirmation).

    For editing nodes/edges prefer edit_workflow (granular ops) — it's far less error-prone.
    Use this only to rename, or to replace the whole graph wholesale. When passing graph,
    read the current one with get_workflow first; the update replaces, it does not merge.
    """
    payload: dict[str, Any] = {"workflow_id": workflow_id}
    if graph is not None:
        payload["graph"] = graph
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "update_workflow",
            "requested_by": _REQUESTED_BY.get(),
            "payload": payload,
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def run_workflow(workflow_id: str, params: dict[str, Any] | None = None, workspace_id: str = "") -> dict[str, Any]:
    """Run a workflow (permission: ai-cost — nodes may spend render/AI budget).
    Requires user confirmation; after approval the result carries the job id."""
    confirmation = _post(
        "/api/confirmations",
        {
            "workspace_id": workspace_id or _default_workspace_id(),
            "tool": "run_workflow",
            "requested_by": _REQUESTED_BY.get(),
            "payload": {"workflow_id": workflow_id, "params": params or {}},
        },
    )
    return _confirmation_reply(confirmation)


@mcp.tool()
def get_confirmation(confirmation_id: str) -> dict[str, Any]:
    """Check a pending confirmation: status becomes executed/rejected/failed after the user decides."""
    confirmation = _get(f"/api/confirmations/{confirmation_id}")
    return {
        "confirmation_id": confirmation["id"],
        "status": confirmation["status"],
        "result": confirmation["result"],
        "error": confirmation["error"],
    }


if __name__ == "__main__":
    mcp.run()
