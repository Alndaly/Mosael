"""One tool registry, served to whichever agent runtime is in use.

There were two. mcp_server.py defines 26 tools for the Claude CLI (which speaks MCP), and
agent-sidecar/src/tools.ts hand-wrote 7 of them again for pi (which does not). The sidecar's
list was a staged build-out — its own header says "S3: read-only set", with the rest promised
for a later slice — and it stopped there. So once pi became the default agent, it silently lost
nineteen tools, including web_search, fetch_url and edit_workflow, all of which were built,
tested and confirmed present in the MCP server while being invisible to the agent that needed
them. Nothing failed loudly; the model just called a tool that "was not found".

Two lists maintained by hand will drift, and the drift is silent, so the fix is to stop having
two. The MCP registry stays the definition. These endpoints expose it — the manifest so an agent
can discover the tools, and the invoke endpoint so it can run one without reimplementing it. A
tool added to mcp_server.py is available to every runtime with no second edit.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import ensure_workspace_member

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent-tools"])


def _registry():
    # Imported lazily: mcp_server sits at the repo root rather than inside the app package, and
    # importing it at module load would make the API's startup depend on the MCP library.
    import mcp_server

    return mcp_server


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolInvocation(BaseModel):
    arguments: dict[str, Any] = {}


@router.get("/agent/tools", response_model=list[ToolSpec])
def list_agent_tools(user: CurrentUser) -> list[ToolSpec]:
    """The tools an agent runtime may offer. Derived from the MCP registry, never a second list."""
    registry = _registry()
    tools = asyncio.run(registry.mcp.list_tools())
    return [
        ToolSpec(
            name=tool.name,
            description=tool.description or "",
            parameters=tool.inputSchema or {"type": "object", "properties": {}},
        )
        for tool in tools
    ]


@router.post("/agent/tools/{name}")
def invoke_agent_tool(
    name: str, body: ToolInvocation, db: DbSession, user: CurrentUser, workspace_id: str = ""
) -> dict[str, Any]:
    """Run one registered tool as the calling user.

    The runtime does not need to know how a tool is implemented — that knowledge living in two
    places is what caused the drift this module exists to end.
    """
    if workspace_id:
        ensure_workspace_member(db, user, workspace_id)
    registry = _registry()
    fn = getattr(registry, name, None)
    if fn is None or not callable(fn) or name.startswith("_"):
        raise HTTPException(status_code=404, detail=f"Tool {name} not found")

    # The tool bodies call back into this API over loopback, so they need the caller's own
    # credential — bound per context, since one process serves many turns at once.
    from app.ai.agent.host import mint_tool_token

    token = mint_tool_token(db, user)
    reset = registry.set_api_token(token)
    try:
        result = fn(**body.arguments)
    except TypeError as exc:  # wrong/missing arguments from the model, not a server fault
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — a failing tool is a result, not a 500
        logger.warning("tool %s failed: %s", name, exc)
        return {"error": str(exc)[:500]}
    finally:
        registry._API_TOKEN.reset(reset)
    return {"result": result}
