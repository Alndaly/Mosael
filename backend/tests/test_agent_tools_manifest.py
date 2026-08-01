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


def _builtin(client) -> list[dict]:
    """The manifest minus expanded plugin tools — those come from the user's own plugins,
    not from mcp_server.py, so registry-drift assertions must not include them."""
    return [tool for tool in _manifest(client) if not tool["name"].startswith("plugin__")]


def test_the_manifest_is_the_mcp_registry_exactly() -> None:
    """The guard against the drift that caused this. If a tool is added to mcp_server.py it
    appears here with no second edit; if this ever diverges, something grew a second list.

    The two plugin meta-tools are the one deliberate subtraction: plugin tools are expanded
    into the manifest as first-class entries, so list_plugin_tools/invoke_plugin_tool would be
    a second path to the same capability. They stay registered for MCP clients, which do not
    get the expansion."""
    import asyncio

    from app.api.routes.agent_tools import _PLUGIN_META_TOOLS

    client = fresh_client()
    served = {tool["name"] for tool in _builtin(client)}
    registered = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert served == registered - _PLUGIN_META_TOOLS
    assert _PLUGIN_META_TOOLS <= registered, "MCP 客户端仍然靠这两个元工具发现插件"
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


def test_high_risk_tool_descriptions_disambiguate_common_misuse() -> None:
    """The descriptions are the model's routing table. Ambiguous neighbors must explicitly
    say what they are NOT for, otherwise the agent will pick the nearest-sounding tool."""
    client = fresh_client()
    descriptions = {tool["name"]: tool["description"] for tool in _builtin(client)}

    assert "Do NOT use for workflow" in descriptions["edit_timeline"]
    assert "use edit_workflow" in descriptions["edit_timeline"]
    assert "Do NOT use for video" in descriptions["edit_workflow"]
    assert "use edit_timeline" in descriptions["edit_workflow"]
    assert "NOT for routine" in descriptions["update_workflow"]
    assert "use edit_workflow" in descriptions["update_workflow"]

    assert "Do NOT use for knowledge-base" in descriptions["list_assets"]
    assert "Do NOT use for media assets" in descriptions["search_kb"]
    assert "Do NOT use for media asset tags" in descriptions["create_kb_note"]
    assert "Do NOT use for KB document tags" in descriptions["update_asset_tags"]

    assert "Do NOT use for running visual workflows" in descriptions["render_sequence"]
    assert "Do NOT use to edit the workflow graph" in descriptions["run_workflow"]
    assert "Do NOT use to analyze an existing asset" in descriptions["generate_image"]
    assert "Do NOT use for exporting an existing sequence" in descriptions["generate_video"]
    assert "Do NOT use for two-host" in descriptions["generate_audio"]
    assert "use generate_audio" in descriptions["generate_podcast"]


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


def test_workflow_graph_ops_sent_to_edit_timeline_get_recoverable_feedback(monkeypatch) -> None:
    """When the model confuses workflow nodes with timeline clips, the error must teach it
    the right tool instead of leaking the unrelated Sequence validator."""
    client = fresh_client()

    def should_not_post(*_args, **_kwargs) -> dict:
        raise AssertionError("workflow graph ops should be rejected before creating a timeline confirmation")

    monkeypatch.setattr(mcp_server, "_post", should_not_post)
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    res = client.post(
        "/api/agent/tools/edit_timeline",
        json={
            "arguments": {
                "sequence_id": None,
                "workspace_id": workspace_id,
                "operations": [{"kind": "remove_node", "node_id": "kb-search-1"}],
            }
        },
    )

    assert res.status_code == 200, res.text
    error = res.json()["error"]
    assert "edit_workflow" in error
    assert "remove_node" in error
    assert "Sequence not found" not in error


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


def test_the_manifest_is_enough_to_build_a_tool_from() -> None:
    """The sidecar constructs its tools from this at startup, so each entry has to be
    self-sufficient: a name to call, a description the model chooses on, and a schema it can
    fill in. A missing piece is worse than a missing tool — the model calls it wrongly instead
    of not at all."""
    client = fresh_client()
    for tool in _manifest(client):
        assert tool["name"] and not tool["name"].startswith("_")
        assert tool["description"].strip()
        schema = tool["parameters"]
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties", {}), dict)


def test_asset_tagging_is_reachable_by_the_agent() -> None:
    """It was implemented and registered, and the runtime could not see it — the whole reason
    the manifest exists."""
    client = fresh_client()
    names = {tool["name"] for tool in _manifest(client)}
    for expected in ("update_asset_tags", "list_workflows", "search_kb", "web_search"):
        assert expected in names, f"{expected} is not offered to the agent"


def test_the_declared_schema_matches_what_the_function_accepts() -> None:
    """The manifest is a contract a runtime builds calls from, so it has to be exact.

    The sidecar reads `properties` to decide which arguments to fill in — it supplies
    workspace_id only to tools that declare it. It first supplied it to every tool, and the
    tools are plain Python functions, so an argument they do not accept is a TypeError rather
    than an ignored extra: web_search and analyze_asset failed on their first call. Drift in
    either direction breaks a caller that trusted the schema.
    """
    import inspect

    client = fresh_client()
    for tool in _builtin(client):
        fn = getattr(mcp_server, tool["name"])
        accepted = set(inspect.signature(fn).parameters)
        declared = set(tool["parameters"].get("properties", {}))
        assert declared <= accepted, (
            f"{tool['name']} declares {sorted(declared - accepted)} which it does not accept"
        )
        # Required arguments must be declared, or a caller cannot know to send them.
        required = {
            name
            for name, param in inspect.signature(fn).parameters.items()
            if param.default is inspect.Parameter.empty
        }
        assert required <= declared, (
            f"{tool['name']} requires {sorted(required - declared)} but does not declare it"
        )


def test_workspace_scoped_tools_declare_workspace_id() -> None:
    """This is the flag the sidecar branches on when filling in the turn's workspace."""
    client = fresh_client()
    declared = {
        tool["name"]: set(tool["parameters"].get("properties", {})) for tool in _builtin(client)
    }
    for scoped in ("list_assets", "list_projects", "search_kb", "list_workflows"):
        assert "workspace_id" in declared[scoped], f"{scoped} lost its workspace_id parameter"
    for unscoped in ("web_search", "fetch_url", "analyze_asset"):
        assert "workspace_id" not in declared[unscoped], (
            f"{unscoped} now declares workspace_id; the sidecar will start sending it"
        )


def test_confirmation_gated_tools_are_marked_in_the_manifest() -> None:
    """runtime 从元数据生成确认等待逻辑,不再按名字手写第二份工具。少标 = 静默丢确认门,
    多标 = 对着普通结果空等确认卡——两个方向都必须钉死。"""
    client = fresh_client()
    marked = {tool["name"] for tool in _builtin(client) if tool.get("confirmation")}
    assert marked == set(mcp_server.CONFIRMATION_TOOLS)
    # 会真实创建确认卡的核心变更工具必须在列
    for name in ("edit_timeline", "render_sequence", "generate_image", "generate_video", "generate_audio", "generate_podcast"):
        assert name in marked


def test_requested_by_reaches_the_confirmation_card(monkeypatch) -> None:
    """sidecar 经 invoke 通道调用时,确认卡显示的请求方应是它自己(pi-agent),
    而不是注册表默认的 mcp-agent。

    工具体经 loopback HTTP 回连后端;TestClient 没有真实端口,把 _post 路由回
    TestClient 本身——链路其余部分(invoke → 工具 → 确认卡)保持真实。"""
    client = fresh_client()

    def fake_post(path: str, payload: dict) -> dict:
        res = client.post(path, json=payload)
        assert res.status_code < 300, res.text
        return res.json()

    monkeypatch.setattr(mcp_server, "_post", fake_post)
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": workspace_id, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": workspace_id, "project_id": project["id"], "name": "S"},
    ).json()

    res = client.post(
        "/api/agent/tools/render_sequence",
        json={"arguments": {"sequence_id": sequence["id"], "workspace_id": workspace_id}, "requested_by": "pi-agent"},
    )
    assert res.status_code == 200, res.text
    result = res.json()["result"]
    assert result["status"] == "pending"

    card = client.get(f"/api/confirmations/{result['confirmation_id']}").json()
    assert card["requested_by"] == "pi-agent"


def test_generation_models_are_agent_discoverable(monkeypatch) -> None:
    """The agent can only pick provider="comfyui" if something tells it that pair exists —
    list_generation_models is that something, read-only and confirmation-free."""
    import mcp_server

    client = fresh_client()

    def fake_get(path: str, params: dict | None = None) -> object:
        res = client.get(path, params=params)
        assert res.status_code < 300, res.text
        return res.json()

    monkeypatch.setattr(mcp_server, "_get", fake_get)
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    # 生成选项现在直接来自用户配置的连接+模型(不再有内置目录表),所以先配一条。
    profile = client.post(
        "/api/settings/providers",
        json={"name": "本地 ComfyUI", "vendor": "comfyui", "config": {"base_url": "http://127.0.0.1:1"}},
    ).json()
    client.post(
        f"/api/settings/providers/{profile['id']}/models",
        json={"model_id": "my-workflow.json", "enabled": True, "capability_ids": ["image"]},
    )

    manifest = {tool["name"]: tool for tool in _manifest(client)}
    assert manifest["list_generation_models"]["confirmation"] is False
    res = client.post(
        "/api/agent/tools/list_generation_models",
        json={"arguments": {"kind": "image"}, "requested_by": "pi-agent"},
    )
    assert res.status_code == 200, res.text
    pairs = {(m["provider"], m["model"]) for m in res.json()["result"]}
    # 智能体看到的就是用户配的那份 —— 以前它看的是内置目录,里面有个叫 workflow 的假模型 id。
    assert ("comfyui", "my-workflow.json") in pairs
    assert workspace_id  # workspace 仅为初始化,断言防未用警告


def test_多给一个键不会让整轮白跑() -> None:
    """回归:模型给 update_plan 传了个顶层 `status`(它的每个 step 里确实有 status,模型把它
    抬了一层),`fn(**arguments)` 抛 TypeError,整次调用 422 —— 而它想做的事完全清楚。

    直接测收敛函数:走路由的话工具体会经回环再打一次 HTTP,测试进程里没有在听的服务器,
    断言就落到了 401 上,证明不了参数这一步。"""
    from app.api.routes.agent_tools import _fit_arguments

    def update_plan(steps: list) -> dict:
        return {"steps": steps}

    fitted, dropped = _fit_arguments(update_plan, {"steps": [{"step": "第一步"}], "status": "in_progress"})
    assert fitted == {"steps": [{"step": "第一步"}]}
    assert dropped == ["status"]


def test_带_kwargs_的工具原样放行() -> None:
    from app.api.routes.agent_tools import _fit_arguments

    def anything(**kwargs) -> dict:
        return kwargs

    fitted, dropped = _fit_arguments(anything, {"whatever": 1})
    assert fitted == {"whatever": 1} and dropped == []


def test_必填参数拼错仍然报错_并说明接受哪些参数() -> None:
    """把必填参数拼错也表现为"多了一个不认识的键"。这时静默丢弃会让工具带着默认值跑起来,
    做的是另一件事 —— 所以照样报错,而且要说清这个工具接受什么。"""
    from tests.util import fresh_client

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    response = client.post("/api/agent/tools/forget", json={"arguments": {"memoryId": "x"}})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "memory_id" in detail
