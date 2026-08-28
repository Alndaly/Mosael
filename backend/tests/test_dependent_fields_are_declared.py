"""结构性约束:**子字段的值不能比它依赖的父字段活得久。**

换了供应商配置,模型栏里还挂着上一家的那个 —— 界面看着完全正常(两个下拉各自都有值),
跑起来才报错。用户报的原话:「更新了供应商 模型可能依然是原先的模型 导致两者不匹配」。

依赖声明在**后端**(NODE_TYPES 的 depends_on),不是前端一张写死的表:插件节点是运行时才
知道的,写死的表永远覆盖不到它们 —— 这个仓库已经因为同一个形状修过好几次了。
"""

from __future__ import annotations

RATCHET = True


def test_成对出现的选择器都声明了依赖() -> None:
    """父子对:换父的时候子必须失效。这里钉住已知的四对都还声明着。"""
    from app.domain.workflows import NODE_TYPES

    expected = {
        ("llm", "model"): "profile_id",
        ("ai_generate", "model"): "provider",
        ("plugin_tool", "tool_name"): "plugin_id",
        ("plugin_tool", "instance_id"): "plugin_id",
    }
    for (node, key), parent in expected.items():
        spec = NODE_TYPES[node]["config"][key]
        assert spec.get("depends_on") == parent, f"{node}.{key} 该跟着 {parent} 走,现在是 {spec.get('depends_on')}"


def test_依赖指向的父字段真的存在() -> None:
    """指向一个不存在的键 = 永远不会触发的清理,而它看起来是配好的。"""
    from app.domain.workflows import NODE_TYPES

    broken = [
        f"{node}.{key} -> {spec['depends_on']}"
        for node, meta in NODE_TYPES.items()
        for key, spec in (meta.get("config") or {}).items()
        if spec.get("depends_on") and spec["depends_on"] not in (meta.get("config") or {})
    ]
    assert not broken, f"这些依赖指向了本节点没有的字段:{broken}"


def test_依赖发到了接口上() -> None:
    """在后端声明但没发出去,前端就没法照它清理 —— 等于没声明。"""
    from app.api.routes.workflows import _with_data_type

    assert _with_data_type("model", {"type": "string", "depends_on": "profile_id"})["depends_on"] == "profile_id"
    assert "depends_on" not in _with_data_type("model", {"type": "string"})
