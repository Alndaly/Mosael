"""智能体要能做**这个应用能做的事** —— 插件、工作流、剪辑,一样都不少。

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。

已有的 test_agent_workflow_parity 只钉一个方向:「工作流有的,智能体要有」。反过来没人管 ——
于是**智能体有 edit_timeline 而工作流没有对应节点**这件事,缺了很久都没人发现(2026-08 补上)。

这条钉的是另一个方向,而且范围更大:剪辑、插件、工作流这三块的核心动作,智能体都要够得着。
判据不是"有几个工具",是**具体哪几件事**——数量会随重构变,而"能不能编排时间线"不会。

漏一个的后果不是少个功能。模型撞上缺失的能力时**不会说"我没有这个工具"**,它会去凑一个:
实际发生过,用户说「打开浏览器,过五秒后关闭」,而当时没有 sleep,于是它用 browser_wait 去等
一段不可能出现的文本,靠超时充当等待,最后还报了"完成"。
"""

from __future__ import annotations

RATCHET = True

import asyncio

import mcp_server

#: 三块能力,各自的核心动作 → 该由哪个工具承担。
#: 只增不减:某个工具改名了就在这里改,而不是把这一行删掉。
REQUIRED: dict[str, dict[str, str]] = {
    "剪辑": {
        "看时间线": "inspect_sequence",
        "编排时间线": "edit_timeline",
        "导出成片": "render_sequence",
    },
    "插件": {
        "看有哪些插件工具": "list_plugin_tools",
        "调用插件工具": "invoke_plugin_tool",
    },
    "工作流": {
        "看有哪些工作流": "list_workflows",
        "看有哪些节点类型": "list_workflow_node_types",
        "新建": "create_workflow",
        "改图": "edit_workflow",
        "跑一次": "run_workflow",
    },
}


def _tool_names() -> set[str]:
    return {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}


def test_三块能力智能体都够得着() -> None:
    tools = _tool_names()
    missing = [
        f"{area} · {what} → {tool}"
        for area, wants in REQUIRED.items()
        for what, tool in wants.items()
        if tool not in tools
    ]
    assert not missing, "智能体缺这些能力:\n  " + "\n  ".join(missing)


def test_时间线的每种操作智能体都发得出() -> None:
    """工具在不等于能力全 —— edit_timeline 收的是一个操作数组,而**能发哪些操作**由序列域
    的清单说了算。工具的说明里要把它们都列出来,否则模型不知道自己能做什么。"""
    from app.domain.sequences.operations import EDIT_OP_KINDS

    doc = next(t for t in asyncio.run(mcp_server.mcp.list_tools()) if t.name == "edit_timeline").description or ""
    missing = [kind for kind in EDIT_OP_KINDS if kind not in doc]
    assert not missing, f"edit_timeline 的说明里没提这些操作,模型不会用:{missing}"


def test_这道棘轮扫得到东西() -> None:
    """假阴性比红更危险:哪天 list_tools 返回空,上面两条会一起真空通过。"""
    assert len(_tool_names()) >= 40
