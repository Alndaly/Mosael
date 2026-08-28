"""插件节点的表单也要能分「普通 / 高级」。

分档这件事对插件**天然不成立**过一阵子:`Field` / input_schema 里没有承载它的地方,
于是插件节点的表单只能一股脑铺开 —— 而插件恰恰是旋钮最容易多的一类(一个 MCP 工具
动辄十几个可选参数)。

判据和内置节点是同一条:**留空也能跑的才算高级**。这条测试钉住两件事:
声明认得出来,以及「用哪个连接」这种自动兜底的字段本身就该在高级里。
"""

from __future__ import annotations

RATCHET = True


def test_schema_里的_x_advanced_会变成节点的_advanced() -> None:
    from app.domain.plugins.nodes import _config_from_schema

    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜什么"},
            "page": {"type": "integer", "x-advanced": True},
        },
        "required": ["query"],
    }
    config = _config_from_schema(schema)
    assert not config["query"].get("advanced"), "必填的主字段被收进了高级 —— 用户会以为没配好"
    assert config["page"]["advanced"] is True


def test_直接写_advanced_也认() -> None:
    """`x-` 前缀是 JSON Schema 的扩展惯例,但插件作者八成先试不带前缀的那个 ——
    为一个拼写把人挡在门外不值得,两种都收。"""
    from app.domain.plugins.nodes import _config_from_schema

    config = _config_from_schema({"properties": {"raw": {"type": "boolean", "advanced": True}}})
    assert config["raw"]["advanced"] is True


def test_没标的字段不会平白多出一个_advanced() -> None:
    """多写一个 `advanced: False` 会让「有没有声明过」这件事变得没法判断。"""
    from app.domain.plugins.nodes import _config_from_schema

    config = _config_from_schema({"properties": {"q": {"type": "string"}}})
    assert "advanced" not in config["q"]


def test_用哪个连接是高级项() -> None:
    """它的说明就是「留空自动选(仅一个时)」—— 正是「留空也能跑」的定义。"""
    from app.domain.plugins.nodes import node_meta

    meta = node_meta({"name": "t", "input_schema": {"properties": {"q": {"type": "string"}}}})
    assert meta["config"]["instance_id"]["advanced"] is True
