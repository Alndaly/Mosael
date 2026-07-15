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


if __name__ == "__main__":
    mcp.run()
