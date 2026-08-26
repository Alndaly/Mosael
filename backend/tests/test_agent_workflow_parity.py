"""工作流有的能力,智能体也要有。

**为什么这是结构约束而不是一句愿望**:同一个能力只在一个界面上存在,用户会撞上"工作流能做
而对话里做不到"。而模型撞上时**不会说"我没有这个工具"**,它会去凑一个 —— 实际发生过:用户
说「打开浏览器,过五秒后关闭」,而智能体没有 sleep,于是它用 browser_wait 去等一段不可能出现
的文本,靠超时充当等待。时间线上留下一条红色的失败,耗时 22 秒,最后模型还报了"完成"。

所以:节点注册表里每加一个类型,要么给它一个对应的智能体工具,要么在 NOT_A_TOOL 里写清楚
为什么它不需要 —— 只减不增,和数据归属那套棘轮同款。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import asyncio

import mcp_server
from app.domain.workflows import NODE_TYPES

#: 节点类型 → 对应的智能体工具名。
NODE_TO_TOOL: dict[str, str] = {
    "delay": "sleep",
    # 时间线:两侧同名同义。节点收的操作数组和 edit_timeline 工具收的是**同一份清单**
    # (domain/sequences/operations.EDIT_OP_KINDS)—— 不是抄的,是同一个常量。
    "edit_timeline": "edit_timeline",
    "inspect_sequence": "inspect_sequence",
    # 这三个是**同一件事的常用形状**:画布上让人填表比手写一条 insert_clip 好用得多,
    # 而智能体不需要这层 —— 它本来就是在写那条操作。都由 edit_timeline 承担。
    "timeline_append": "edit_timeline",
    "timeline_add_track": "edit_timeline",
    "timeline_clear": "edit_timeline",
    "llm": "",  # 见 NOT_A_TOOL
    "plugin_tool": "",  # 插件工具已展开成一等公民(plugin__<连接>__<工具>),不是固定的一个名字
    "transcribe_asset": "transcribe_asset",
    "export_sequence": "render_sequence",
    "ai_generate": "generate_image",  # 与 generate_video 同一节点的两种 kind
    "publish": "publish_asset",
    "http_request": "http_request",
    "code": "run_code",
    "synthesize_speech": "generate_audio",
    "notify": "notify_workspace",
    "translate": "translate_text",
    "asset_query": "list_assets",
    "asset_tag": "update_asset_tags",
    "asset_update": "update_asset",
    "project_create": "create_project",
    "call_workflow": "run_workflow",
    "browser_open": "browser_open",
    "browser_navigate": "browser_navigate",
    "browser_click": "browser_click",
    "browser_input": "browser_type",
    "browser_upload": "browser_upload",
    "browser_extract": "browser_read",
    "browser_wait": "browser_wait",
    "browser_scroll": "browser_scroll",
    "browser_evaluate": "browser_evaluate",
    "browser_close": "browser_close",
}

#: 不需要对应工具的节点 → 理由。这些是**图的结构**或**模型本身就会做的事**,
#: 给它们造一个工具只会多一层没人用的间接。
NOT_A_TOOL: dict[str, str] = {
    "start": "图的入口,不是一个动作 —— 对话里由用户开口就是开始。",
    "output": "声明工作流的返回值。对话的返回值就是模型的回复。",
    "condition": "分支。模型自己会按结果决定下一步,这正是它比固定图强的地方。",
    "loop_foreach": "循环。同上 —— 模型自己会对一组东西逐个处理。",
    "loop_while": "循环。同上。",
    "subgraph": "把一组节点折叠起来,是画布上的组织手段,对话里没有对应物。",
    "template": "拼字符串。模型自己就在做这件事。",
    "json_extract": "从 JSON 里按路径取值。模型自己会读 JSON。",
    "text_transform": "去空白/大小写/正则。模型自己会做。",
    "llm": "调模型生成文本 —— 智能体本身就是那个模型,再给它一个调模型的工具是套娃。",
    "plugin_tool": "插件工具已展开成一等公民(plugin__<连接>__<工具>),不是固定的一个工具名。",
}


def _agent_tools() -> set[str]:
    return {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}


def test_每个工作流节点要么有对应工具_要么写明为什么不需要() -> None:
    tools = _agent_tools()
    missing: list[str] = []
    for node_type in NODE_TYPES:
        if node_type in NOT_A_TOOL:
            continue
        tool = NODE_TO_TOOL.get(node_type, "")
        if not tool:
            missing.append(f"{node_type}(既没登记工具,也没写在 NOT_A_TOOL 里)")
        elif tool not in tools:
            missing.append(f"{node_type} → {tool}(工具不存在)")
    assert not missing, "工作流有、智能体没有的能力:\n  " + "\n  ".join(missing)


def test_登记表里没有已经删掉的节点或工具() -> None:
    """映射只减不增。留一条指向已删节点的登记,下一个人会以为那个能力还在。"""
    tools = _agent_tools()
    stale_nodes = sorted(set(NODE_TO_TOOL) - set(NODE_TYPES))
    stale_exempt = sorted(set(NOT_A_TOOL) - set(NODE_TYPES))
    stale_tools = sorted({t for t in NODE_TO_TOOL.values() if t and t not in tools})
    assert stale_nodes == [], f"登记了不存在的节点: {stale_nodes}"
    assert stale_exempt == [], f"豁免了不存在的节点: {stale_exempt}"
    assert stale_tools == [], f"登记了不存在的工具: {stale_tools}"


def test_两份确认清单必须一致() -> None:
    """确认门控写在两个地方:mcp_server 的 CONFIRMATION_TOOLS(工具这一侧,决定要不要开卡)
    和后端的 TOOL_DEFS(领域这一侧,决定权限档次和批准后干什么)。

    只加一边不会报错,只会在**用户点批准的那一刻**才炸 —— 而那时智能体已经告诉他"正在做了"。
    (这次就是:三个新工具只加进了 CONFIRMATION_TOOLS,开卡直接 422 Unknown mutating tool。)
    """
    from app.domain.agent.confirmations import TOOL_DEFS

    assert set(mcp_server.CONFIRMATION_TOOLS) == set(TOOL_DEFS)


def test_确认卡的权限档次前端都有文案() -> None:
    """权限档次是用户点批准前唯一会看的那行字。前端按查表取文案,漏掉的档次会原样显示成
    机器名(如 "external"),所以这里守住:每一档都要有 messages.ts 里的键。"""
    from pathlib import Path

    from app.domain.agent.confirmations import TOOL_DEFS

    messages = (Path(__file__).resolve().parents[2] / "frontend/src/app/messages.ts").read_text("utf-8")
    keys = {"edit": "permEdit", "ai-cost": "permAiCost", "render-cost": "permRenderCost", "external": "permExternal"}
    for definition in TOOL_DEFS.values():
        permission = definition["permission"]
        assert permission in keys, f"新权限档次 {permission} 没有前端文案键"
        assert f"{keys[permission]}:" in messages, f"messages.ts 里缺 {keys[permission]}"


def test_改动外面世界的工具都走确认卡() -> None:
    """公开发布、在本机跑代码、向外部发写请求 —— 这三件的后果都不在这个应用里,
    撤不回来。它们必须等用户点头,而不是"跑完了再说"。"""
    assert {"publish_asset", "run_code", "http_request"} <= set(mcp_server.CONFIRMATION_TOOLS)


def test_sleep_有上限() -> None:
    """没有上限的话,模型可以在一轮里睡到用户以为应用挂了 —— 而它并不知道那一端有人在等。

    (这里不真睡满上限:断言的是那个数字本身,以及超限会被夹到上限。)
    """
    assert mcp_server.SLEEP_CAP_SECONDS == 60.0
    assert mcp_server.sleep(0)["slept_seconds"] == 0.0
    assert mcp_server.sleep(-5)["slept_seconds"] == 0.0
