"""循环 / 子图的 `output`、条件循环的 `condition` 按**体内**作用域校验。

这两格在体内解析(见 NESTED_BODY_RAW_KEYS),此前前后端都不看:后端 `_unresolvable_body_refs` 只扫
体里的节点,画布对这两格直接跳过。写错一个节点名,运行时插值成空串 —— 条件循环安静地只跑一轮,
遍历循环交出一列空串。
"""

from __future__ import annotations

from app.domain.workflows import validate_graph


def _graph(container: dict) -> dict:
    return {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "box", **container}],
        "edges": [{"id": "e1", "source": "start", "target": "box"}],
    }


BODY = {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.index}}"}}], "edges": []}


def test_条件循环的条件引用体里没有的节点_运行前就报() -> None:
    errors = validate_graph(_graph({"type": "loop_while", "config": {"body": BODY, "condition": "{{tt.text}}"}}))
    assert errors == ["「循环·条件」的「条件」在里面那一层解析,引用了那里看不见的 tt:那里只看得见 loop 和里面的节点"]


def test_遍历循环的输出引用外层节点_运行前就报() -> None:
    errors = validate_graph(_graph({"type": "loop_foreach", "config": {"items": "a", "body": BODY, "output": "{{start.q}}"}}))
    assert errors == ["「循环·遍历」的「对外输出」在里面那一层解析,引用了那里看不见的 start:那里只看得见 loop、input 和里面的节点"]


def test_条件循环里没有_loop_item() -> None:
    """条件循环只播 `loop.index` —— 输出写 `{{loop.item}}` 运行时就是空串。"""
    errors = validate_graph(_graph({"type": "loop_while", "config": {"body": BODY, "output": "{{loop.item}}"}}))
    assert errors == ["「循环·条件」用到的 loop · item 这里没有:只提供 loop · index"]


def test_引用体内节点和作用域名的都合法() -> None:
    for container in (
        {"type": "loop_while", "config": {"body": BODY, "condition": "{{t.text}}", "output": "{{loop.index}}: {{t.text}}"}},
        {"type": "loop_foreach", "config": {"items": "a", "body": BODY, "output": "{{loop.item}} {{t.text}}"}},
        {"type": "subgraph", "config": {"inputs": {"x": "1"},
                                        "body": {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{input.x}}"}}],
                                                 "edges": []},
                                        "output": "{{t.text}} {{input.x}}"}},
    ):
        assert validate_graph(_graph(container)) == [], container
