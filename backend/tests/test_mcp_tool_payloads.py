"""冒烟测试:**每个工具发出去的载荷,后端接得住。**

背景是一个真实事故。`translate_text` 发的是 `{"text", "target", "source"}`,而 `/api/translate`
要的是 `{"texts": [...], "target_lang"}` —— 每次调用必然 422,而这个工具是随「智能体补齐工作流
全部能力」一起加的,跟着进了一个已经打好的安装包。

已有的两道检查都拦不住它:test_agent_tools_manifest 钉的是「工具出现在清单里」,
test_agent_workflow_parity 钉的是「工作流有的能力智能体也有」—— 两条都只问**存不存在**,
不问**跑不跑得通**。模型撞上 422 时也不会说「这个工具坏了」,它会换个说法再试一次,或者
干脆告诉用户翻译失败。

所以这里问第三个问题:拿着一份最小的合法参数调下去,后端会不会因为**载荷结构**拒绝。
资源不存在(404)、没登录(401)都不算 —— 那是数据问题,不是契约问题;只有 422 且错误指向
请求体字段的,才是这类 bug。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import asyncio
from typing import Any

import mcp_server
from tests.util import fresh_client

#: 工具名 → 一份最小的合法参数。空 dict 表示无参调用。
#: 参数里的资源 id 故意用不存在的值:我们要验的是**载荷形状**,不是数据。
ARGS: dict[str, dict[str, Any]] = {
    "list_projects": {},
    "list_workspaces": {},
    "list_jobs": {},
    "get_current_time": {},
    "list_assets": {},
    "list_workflows": {},
    "list_workflow_node_types": {},
    "list_memories": {},
    "list_generation_models": {},
    "list_plugin_tools": {},
    "list_publish_accounts": {},
    "browser_pool_list": {},
    "translate_text": {"text": "hello", "target": "zh"},
    "create_project": {"name": "冒烟项目"},
    "notify_workspace": {"title": "冒烟通知", "body": "正文"},
    "list_agent_sessions": {},
    "notify_agent_session": {"session_id": "no-such-session", "message": "冒烟通知"},
    "remember": {"content": "冒烟记忆"},
    "sleep": {"seconds": 0},
    "get_job": {"job_id": "no-such-job"},
    "get_workflow": {"workflow_id": "no-such-workflow"},
    "get_confirmation": {"confirmation_id": "no-such-confirmation"},
    "inspect_sequence": {"sequence_id": "no-such-sequence"},
    "analyze_asset": {"asset_id": "no-such-asset", "question": "这是什么"},
    "transcribe_asset": {"asset_id": "no-such-asset"},
    "get_transcript": {"asset_id": "no-such-asset"},
    "update_asset": {"asset_id": "no-such-asset", "name": "改个名"},
    "update_asset_tags": {"asset_id": "no-such-asset", "tags": ["a"]},
    "forget": {"memory_id": "no-such-memory"},
    "update_plan": {"steps": [{"title": "第一步", "status": "pending"}]},
    "invoke_plugin_tool": {"tool_name": "no-such-tool", "arguments": {}},
    "browser_navigate": {"session_id": "no-such-session", "url": "https://example.test"},
    "browser_click": {"session_id": "no-such-session", "selector": "#x"},
    "browser_type": {"session_id": "no-such-session", "selector": "#x", "text": "hi"},
    "browser_read": {"session_id": "no-such-session"},
    "browser_wait": {"session_id": "no-such-session", "text": "x", "timeout_ms": 1},
    "browser_scroll": {"session_id": "no-such-session", "dy": 100},
    "browser_upload": {"session_id": "no-such-session", "selector": "#f", "asset_id": "no-such-asset"},
    "browser_evaluate": {"session_id": "no-such-session", "expression": "1"},
    "browser_close": {"session_id": "no-such-session"},
}

#: 不冒烟的工具 → 理由。只减不增。
SKIP: dict[str, str] = {
    "web_search": "会打真实外网。",
    "fetch_url": "会打真实外网。",
    # 探测链接这一步就要打外网(yt-dlp 去问站点),而且没探到条目会先抛,根本走不到发载荷那步。
    # 它发的两个载荷由 tests/test_url_import.py 直接盯着后端那一侧。
    "import_media_from_url": "探测链接要打真实外网。",
}


def _route_through(monkeypatch, client) -> list[tuple[str, str, int, str]]:
    """把 mcp_server 的 HTTP 出口接到 TestClient 上,并记下每次往返。"""
    seen: list[tuple[str, str, int, str]] = []

    def call(method: str, path: str, **kwargs):
        response = client.request(method, path, **kwargs)
        seen.append((method, path, response.status_code, response.text[:400]))
        mcp_server._raise_with_detail(response)
        return response.json() if response.content else None

    monkeypatch.setattr(mcp_server, "_get", lambda path, params=None: call("GET", path, params=params))
    monkeypatch.setattr(mcp_server, "_post", lambda path, payload: call("POST", path, json=payload))
    monkeypatch.setattr(mcp_server, "_patch", lambda path, payload: call("PATCH", path, json=payload))
    monkeypatch.setattr(mcp_server, "_put", lambda path, payload: call("PUT", path, json=payload))
    monkeypatch.setattr(mcp_server, "_delete", lambda path: call("DELETE", path))
    return seen


def _is_shape_rejection(status: int, body: str) -> bool:
    """422 且错误指向请求体 —— 这就是「工具发的东西后端不认识」。

    别的 422(领域校验,如「素材不存在」)不算:那是数据问题,而这个测试传的本来就是
    不存在的 id。
    """
    return status == 422 and '"body"' in body


def test_每个工具发出去的载荷后端都接得住(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 工具默认取第一个工作区
    seen = _route_through(monkeypatch, client)

    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    broken: list[str] = []
    for name, args in ARGS.items():
        if name not in tools:
            continue
        before = len(seen)
        try:
            getattr(mcp_server, name)(**args)
        except Exception:  # noqa: BLE001 — 领域错误是预期的(传的都是不存在的 id)
            pass
        for method, path, status, body in seen[before:]:
            if _is_shape_rejection(status, body):
                broken.append(f"{name} → {method} {path}: {body[:200]}")
    assert broken == [], "这些工具发的载荷后端不认识(必然每次都失败):\n  " + "\n  ".join(broken)


def test_每个直接执行的工具要么冒烟要么写明为什么不冒烟() -> None:
    """只减不增。新加一个工具却不给它一份参数,这条就红 —— 而那正是 translate_text 溜过去的路。"""
    tools = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    direct = tools - set(mcp_server.CONFIRMATION_TOOLS)
    uncovered = sorted(direct - set(ARGS) - set(SKIP))
    assert uncovered == [], "这些工具没有冒烟参数,也没写明为什么不需要:\n  " + "\n  ".join(uncovered)


def test_冒烟清单里没有已经删掉的工具() -> None:
    tools = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    stale = sorted((set(ARGS) | set(SKIP)) - tools)
    assert stale == [], f"登记了不存在的工具: {stale}"
