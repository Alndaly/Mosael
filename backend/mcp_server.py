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

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = os.environ.get("MIBU_API", "http://127.0.0.1:8800")
API_TOKEN = os.environ.get("MIBU_TOKEN", "")

mcp = FastMCP("mibu")


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    with httpx.Client(base_url=API_BASE, timeout=15, headers=headers) as client:
        response = client.get(path, params=params)
        response.raise_for_status()
        return response.json()


def _post(path: str, payload: dict[str, Any]) -> Any:
    headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
    with httpx.Client(base_url=API_BASE, timeout=30, headers=headers) as client:
        response = client.post(path, json=payload)
        response.raise_for_status()
        return response.json()


def _default_workspace_id() -> str:
    workspaces = _get("/api/workspaces")
    if not workspaces:
        raise ValueError("No workspace available")
    return workspaces[0]["id"]


def _confirmation_reply(confirmation: dict[str, Any]) -> dict[str, Any]:
    return {
        "confirmation_id": confirmation["id"],
        "status": confirmation["status"],
        "permission": confirmation["permission"],
        "summary": confirmation["summary"],
        "message": "等待用户在 Mibu 中确认。用 get_confirmation 轮询结果；批准后 result 才会填充。",
    }


@mcp.tool()
def list_assets(workspace_id: str = "") -> list[dict[str, Any]]:
    """List media assets in a workspace (id, name, kind, source, duration).

    Leave workspace_id empty to use the first workspace.
    """
    if not workspace_id:
        workspaces = _get("/api/workspaces")
        if not workspaces:
            return []
        workspace_id = workspaces[0]["id"]
    assets = _get("/api/assets", {"workspace_id": workspace_id})
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
            "requested_by": "mcp-agent",
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
            "requested_by": "mcp-agent",
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
            "requested_by": "mcp-agent",
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
            "requested_by": "mcp-agent",
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
