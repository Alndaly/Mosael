"""自己声明了 `input` 的「执行脚本」,代码字段的改写不碰它;1.8.1 已经改了的改回原文,修订说明里点名。

## 现场

「执行脚本」包在 `with ({input: …}) { 脚本 }` 里跑。脚本自己写了 `const input = …`(或叫 input 的参数)时,
它盖住交进来的那个 —— 改写成 `input.k` 读到的是脚本自己的变量,静默取空,而且看不出来。
"""

from __future__ import annotations

from app.domain.workflows.graph_upgrade import upgrade_graph

OWN_INPUT = "const input = document.querySelector('#q'); input.value + '{{t.text}}'"


def _graph(expression: str, extra: dict | None = None) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "t", "type": "template", "config": {"template": "后缀"}},
            {"id": "js", "type": "browser_evaluate", "config": {"session": "s", "expression": expression, **(extra or {})}},
            {"id": "plain", "type": "browser_evaluate", "config": {"session": "s", "expression": "'{{t.text}}'"}},
        ],
        "edges": [],
    }


def _js(graph: dict, node_id: str = "js") -> dict:
    return next(node for node in graph["nodes"] if node["id"] == node_id)["config"]


def test_图升级不改自己声明了input的脚本_别的照改() -> None:
    upgraded = upgrade_graph(_graph(OWN_INPUT))
    assert _js(upgraded) == {"session": "s", "expression": OWN_INPUT}
    assert _js(upgraded, "plain")["input"] == {"t_text": "{{t.text}}"}
