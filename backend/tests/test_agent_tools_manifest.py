"""One tool registry, exposed to whichever agent runtime is in use.

There were two. mcp_server.py defines the tools for the Claude CLI, and the pi sidecar
hand-wrote seven of them again because pi does not speak MCP. That second list was a staged
build-out ("S3: read-only set") that stopped there, so when pi became the default agent it
silently lost nineteen tools — web_search, fetch_url, edit_workflow among them, all built and
tested and confirmed present in the MCP server while being invisible to the agent. The model
just reported that a tool "was not found".

Two hand-maintained lists drift, and silently. These tests pin that there is now one.
"""

from __future__ import annotations

import mcp_server
from tests.util import fresh_client


def _manifest(client) -> list[dict]:
    res = client.get("/api/agent/tools")
    assert res.status_code == 200, res.text
    return res.json()


def test_the_manifest_is_the_mcp_registry_exactly() -> None:
    """The guard against the drift that caused this. If a tool is added to mcp_server.py it
    appears here with no second edit; if this ever diverges, something grew a second list."""
    import asyncio

    client = fresh_client()
    served = {tool["name"] for tool in _manifest(client)}
    registered = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert served == registered
    assert len(served) > 20, "the registry looks truncated"


def test_the_tools_the_sidecar_was_missing_are_in_the_manifest() -> None:
    client = fresh_client()
    names = {tool["name"] for tool in _manifest(client)}
    # Each of these was implemented during this project and never reached the pi agent.
    for missing in ("analyze_asset", "web_search", "fetch_url", "edit_workflow", "search_kb"):
        assert missing in names, f"{missing} still not offered to the agent"


def test_every_tool_carries_a_description_and_a_schema() -> None:
    """A runtime builds its tool definitions from this, and a model chooses from the
    descriptions — an entry missing either is worse than absent, because it will be called
    wrongly rather than not at all."""
    client = fresh_client()
    for tool in _manifest(client):
        assert tool["description"].strip(), f"{tool['name']} has no description"
        assert tool["parameters"].get("type") == "object", f"{tool['name']} has no object schema"


def test_an_unknown_tool_is_a_404() -> None:
    client = fresh_client()
    assert client.post("/api/agent/tools/no_such_tool", json={"arguments": {}}).status_code == 404


def test_private_helpers_are_not_callable() -> None:
    """mcp_server's module namespace holds _get/_post/_default_workspace_id too. Dispatching by
    getattr without this would expose them as tools."""
    client = fresh_client()
    for private in ("_get", "_post", "_patch", "_default_workspace_id"):
        res = client.post(f"/api/agent/tools/{private}", json={"arguments": {}})
        assert res.status_code == 404, f"{private} was reachable"


def test_a_failing_tool_is_a_result_not_a_500() -> None:
    """A tool that raises is information for the model to act on, not a server fault — the
    turn should continue."""
    client = fresh_client()
    res = client.post("/api/agent/tools/analyze_asset", json={"arguments": {"asset_id": "nope"}})
    assert res.status_code == 200
    assert "error" in res.json()


def test_the_token_is_context_bound_not_global() -> None:
    """One process serves many turns at once. A module-level token would leak one caller's
    credential into another's request."""
    import contextvars

    assert isinstance(mcp_server._API_TOKEN, contextvars.ContextVar)

    def read_in_context(value: str) -> str:
        reset = mcp_server.set_api_token(value)
        try:
            return mcp_server._auth_headers()["Authorization"]
        finally:
            mcp_server._API_TOKEN.reset(reset)

    ctx_a = contextvars.copy_context()
    ctx_b = contextvars.copy_context()
    assert ctx_a.run(read_in_context, "token-a") == "Bearer token-a"
    assert ctx_b.run(read_in_context, "token-b") == "Bearer token-b"
    # Neither leaked into the ambient context.
    assert "Authorization" not in mcp_server._auth_headers() or mcp_server._API_TOKEN.get() == ""
