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
    "list_boards": {},
    "list_board_producers": {},
    "list_workflow_node_types": {},
    "list_memories": {},
    "search_notes": {"query": "灵感"},
    # 技能(ADR 0040):内置的那几个每个工作区都有,不用造数据。
    "use_skill": {"name": "creative-board"},
    "list_skills": {"name": "creative-board"},
    "read_skill_file": {"name": "creative-board", "path": "SKILL.md"},
    "read_note": {"note_id": "no-such-note"},
    "list_scenes": {},
    "list_entities": {"kind": "character"},
    "get_entity": {"entity_id": "no-such-entity"},
    "create_entity": {"kind": "character", "name": "冒烟人物", "prompt": "黑色短发"},
    "attach_entity_reference": {"entity_id": "no-such-entity", "asset_id": "no-such-asset", "role": "front"},
    "list_scene_models": {},
    "get_scene": {"scene_id": "no-such-scene"},
    "create_scene": {"name": "Scene smoke test"},
    "edit_scene": {"scene_id": "no-such-scene", "base_revision": 1},
    "render_scene_references": {"scene_id": "no-such-scene", "shot_id": "shot-1"},
    "view_scene": {"scene_id": "no-such-scene", "views": ["shot", "top"]},
    # 没有 Blender 连接:后端答 404/409,但载荷形状照样要被路由接住。
    "blender_inspect": {},
    "blender_look": {"views": ["top", "camera"], "objects": ["Roof"], "shading": "solid"},
    "blender_import_to_scene": {"scene_id": "no-such-scene", "base_revision": 1, "objects": ["Roof"],
                                "position": [0, 0, 0]},
    "blender_send_scene": {"scene_id": "no-such-scene", "shot_id": "shot-1"},
    # ComfyUI 工作台的智能体(ADR 0042):没有 ComfyUI 连接,领域答「你还没有接 ComfyUI」,载荷形状照样要接得住。
    "comfy_canvas_read": {},
    "comfy_locate": {"node": "12:5"},
    "comfy_check": {"job_id": "no-such-job", "last_error": "#3 Value not in list"},
    "comfy_templates": {"query": "qwen image edit", "limit": 3},
    "comfy_template": {"name": "image_qwen_image_2_1_image_edit"},
    "comfy_node_types": {"classes": ["KSampler"]},
    "plugin_tools": {"query": "古风", "tool": "人像/古风.json", "input": "lora_name_10"},
    "comfy_node_packs": {},
    "comfy_node_pack_search": {"node_types": ["WanVideoSampler"]},
    "comfy_node_pack_info": {"pack_id": "rgthree-comfy"},
    "comfy_canvas_new": {"template": "image_qwen_image_2_1_image_edit", "name": "Qwen 编辑",
                         "ops": [{"op": "set_widget", "node": "459", "widget": "steps", "value": 30}]},
    "create_note": {"title": "冒烟笔记", "markdown": "正文"},
    "append_note": {"note_id": "no-such-note", "base_revision": 1, "markdown": "补充"},
    # 问一个形状合法的问题:载荷要能被 /api/agent/questions 接住。没有会话上下文时它会
    # 早退(返回 error),那条路不打后端 —— 所以这里主要盯的是**有**会话时那一份形状。
    "ask_user": {
        "questions": [
            {
                "header": "去向",
                "question": "这段成片发到哪儿?",
                "options": [{"label": "B站", "description": "投稿到已登录的账号"}, {"label": "先不发"}],
            }
        ]
    },
    "get_answer": {"question_id": "does-not-exist"},
    "list_generation_models": {},
    "list_speech_engines": {},
    # 空参 = 全部能力、全部执行面。真正会 422 的是 surface,而它在工具里就地校验了。
    "list_provider_models": {},
    # 没有界面上下文时它自己回一句"跳不了" —— 冒烟正好走那条路,不发请求。
    "open_view": {"view": "home"},
    "list_publish_accounts": {},
    "list_publish_tasks": {},
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
    "get_board": {"board_id": "no-such-board"},
    "get_confirmation": {"confirmation_id": "no-such-confirmation"},
    "inspect_sequence": {"sequence_id": "no-such-sequence"},
    "analyze_asset": {"asset_id": "no-such-asset", "question": "这是什么"},
    "read_document": {"asset_id": "no-such-asset", "first": 1, "last": 2},
    "analyze_document_pages": {"asset_id": "no-such-asset", "pages": [1], "question": "版式怎样"},
    "transcribe_asset": {"asset_id": "no-such-asset"},
    "get_transcript": {"asset_id": "no-such-asset"},
    "update_asset": {"asset_id": "no-such-asset", "name": "改个名"},
    "update_asset_tags": {"asset_id": "no-such-asset", "tags": ["a"]},
    "forget": {"memory_id": "no-such-memory"},
    "update_plan": {"steps": [{"title": "第一步", "status": "pending"}]},
    "browser_navigate": {"session_id": "no-such-session", "url": "https://example.test"},
    "browser_click": {"session_id": "no-such-session", "selector": "#x"},
    "browser_type": {"session_id": "no-such-session", "selector": "#x", "value": "hi"},
    "browser_read": {"session_id": "no-such-session"},
    "browser_wait": {"session_id": "no-such-session", "text": "x", "timeout_ms": 1},
    "browser_scroll": {"session_id": "no-such-session", "dy": 100},
    "browser_screenshot": {"session_id": "no-such-session", "mode": "full"},
    "browser_page": {"session_id": "no-such-session", "operation": "switch", "by": "title", "value": "x"},
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


def _route_through(monkeypatch, client) -> None:
    """让直接调领域的工具认得出「这次调用是谁」:就是这个 TestClient 登录的那个人 —— 和经
    /api/agent/tools 调用时同一个身份。工具不再经 HTTP 回连,所以没有往返可记。"""
    import contextvars

    from app.core.db import SessionLocal
    from app.core.security import find_session

    with SessionLocal() as db:
        caller = find_session(db, client.headers["Authorization"].removeprefix("Bearer ")).user_id
    monkeypatch.setattr(mcp_server, "_CALLER_ID", contextvars.ContextVar("test_caller", default=caller))


def _is_shape_rejection(exc: BaseException) -> bool:
    """这次失败是**契约**问题,不是数据问题。

    工具直接调领域之后,「载荷形状不对」换了两种样子:给用例传了它不认识的参数(TypeError),或者
    按工具自己的最小参数造出来的请求模型过不了校验(ValidationError)。资源不存在、没权限这类领域错误
    不算 —— 这个测试传的本来就是不存在的 id。
    """
    from pydantic import ValidationError

    return isinstance(exc, (TypeError, ValidationError))


def test_每个工具发出去的载荷后端都接得住(monkeypatch) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 工具默认取第一个工作区
    _route_through(monkeypatch, client)

    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    broken: list[str] = []
    for name, args in ARGS.items():
        if name not in tools:
            continue
        try:
            getattr(mcp_server, name)(**args)
        except Exception as exc:  # noqa: BLE001 — 领域错误是预期的(传的都是不存在的 id)
            if _is_shape_rejection(exc):
                broken.append(f"{name}: {type(exc).__name__}: {str(exc)[:200]}")
    assert broken == [], "这些工具调领域的方式不对(必然每次都失败):\n  " + "\n  ".join(broken)


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


def test_节点类型先返回轻量目录_指定类型才返回完整配置(monkeypatch) -> None:
    rows = [
        {
            "type": "llm",
            "label": "LLM",
            "description": "调用语言模型",
            "category": "AI",
            "config": {"model": {"type": "string"}, "prompt": {"type": "textarea"}},
            "outputs": ["text", "json"],
            "output_types": {"text": "text"},
            "output_labels": {"text": "文本"},
            "plugin_name": "",
            "tool_name": "",
        }
    ]
    monkeypatch.setattr(mcp_server, "_use_case", lambda *_a, **_k: rows)

    catalog = mcp_server.list_workflow_node_types()
    assert catalog == [
        {
            "type": "llm",
            "label": "LLM",
            "category": "AI",
            "config_fields": ["model", "prompt"],
            "outputs": ["text", "json"],
            "plugin_name": "",
            "tool_name": "",
        }
    ]
    assert mcp_server.list_workflow_node_types("llm") == rows[0]
