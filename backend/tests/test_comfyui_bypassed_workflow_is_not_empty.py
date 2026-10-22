"""一张**全部节点被 ⌘B 旁路**的工作流,不是「空的」工作流。

现场(2026-10-22,维护者截图):工作流库右侧写着「工作流是空的」,可那张图有 106 个节点、16 个模型 ——
因为 ComfyUI 的旁路(mode 4)与静音(mode 2)节点**不进 API 图**,而 `convert.to_api` 把它们全剔掉之后
得到一张空图,于是被当成「文件里没有节点」。

两者要分开说:空文件 = 工作流是空的;全被旁路 = 现在没有会跑的节点,**取消旁路就又能跑**。
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import graph  # noqa: E402  (插件的顶层模块:和它在 ComfyUI 插件里被加载时同一个)


def _node(node_id: str, mode: int) -> dict:
    return {"id": node_id, "type": "KSampler", "mode": mode, "inputs": [], "outputs": []}


def test_all_bypassed_says_it_is_not_empty() -> None:
    ui = {"nodes": [_node("1", 4), _node("2", 4), _node("3", 4)], "links": []}
    assert graph.dormant_counts(ui) == (3, 3, 0)
    message = str(graph.dormant_reason(ui, "zh"))
    assert "不是空的" in message
    assert "3 个节点全部被旁路" in message
    assert "工作流是空的" not in message, "全被旁路时不能说成「空的」——那正是维护者截图里那句错的"


def test_mixed_bypass_and_mute_are_both_named() -> None:
    ui = {"nodes": [_node("1", 4), _node("2", 2)], "links": []}
    assert graph.dormant_counts(ui) == (2, 1, 1)
    message = str(graph.dormant_reason(ui, "zh"))
    assert "旁路" in message and "静音" in message


def test_a_genuinely_empty_file_still_says_empty() -> None:
    assert str(graph.dormant_reason({"nodes": [], "links": []}, "zh")) == "工作流是空的"
    assert str(graph.dormant_reason({}, "zh")) == "工作流是空的"


def test_a_partly_bypassed_graph_gets_no_reason_of_its_own() -> None:
    """还有节点会跑 → 交给调用方按自己的语义填(不能因为「有几个被旁路」就说整张图不跑)。"""
    ui = {"nodes": [_node("1", 4), _node("2", 0)], "links": []}
    assert graph.dormant_reason(ui, "zh") == ""


def test_the_english_side_says_the_same_thing() -> None:
    ui = {"nodes": [_node("1", 4)], "links": []}
    message = str(graph.dormant_reason(ui, "en"))
    assert "not empty" in message and "bypassed" in message
