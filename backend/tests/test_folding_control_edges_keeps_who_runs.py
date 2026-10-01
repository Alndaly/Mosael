"""规范化折掉多余的控制边,不许改变「谁该跑」。

## 现场

规范化把精确引用 `{{A.text}}` 升级成数据边之后,会把同一对节点间无 handle 的控制边当多余的折掉 —— 数据边本身
也排先后。可引擎判「该不该跑」时,有控制边只看控制边,只有数据边时看数据边(任一来源跑了就跑)。T 的控制边只来自
条件分支里的 A、另有一条数据边来自分支外的 B 时,折掉 A→T 就把「A 跑了才跑」改成了「A 或 B 跑了就跑」:
条件为假、A 被跳过,T 照样拿着空的 A.text 跑了。

修法:T 另有带路由语义的控制边(条件的「真」出口)时,只排先后的那几条照旧折掉、由路由边说了算(官方模板靠
这个:「这一拍有画外音才放音轨」);T 的控制边全是只排先后的,只在数据边的来源恰好就是它们的来源时折。
"""

from __future__ import annotations

from tests.util import fresh_client, wait_status


def _graph(*, with_b: bool) -> dict:
    body = "{{B.text}}" if with_b else "固定的正文"
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"has_voice": "no"}}},
            {"id": "c", "type": "condition", "config": {"left": "{{start.has_voice}}", "op": "equals", "right": "yes"}},
            {"id": "A", "type": "template", "config": {"template": "口播稿"}},
            {"id": "B", "type": "template", "config": {"template": "画面"}},
            {"id": "T", "type": "notify", "config": {"title": "{{A.text}}", "body": body}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "c"},
            {"id": "e2", "source": "c", "target": "A", "source_handle": "true"},
            {"id": "e3", "source": "start", "target": "B"},
            {"id": "e4", "source": "A", "target": "T"},
        ],
    }


def _save_and_run(graph: dict) -> tuple[dict, dict]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "分支", "graph": graph}).json()
    started = client.post(f"/api/workflows/{saved['id']}/run", json={"params": {}}).json()
    assert wait_status(client, started["id"]) == "succeeded"
    return saved["graph"], client.get(f"/api/jobs/{started['id']}").json()["result"]["context"]


def _pairs(graph: dict, kind: str) -> set[tuple[str, str]]:
    return {(edge["source"], edge["target"]) for edge in graph["edges"] if edge.get("kind", "control") == kind}


def test_T另有来自分支外B的数据_A到T的控制边留着_A被跳过时T也跳过() -> None:
    saved, context = _save_and_run(_graph(with_b=True))
    assert ("A", "T") in _pairs(saved, "control"), "折掉它,T 就变成「A 或 B 跑了就跑」"
    assert {("A", "T"), ("B", "T")} <= _pairs(saved, "data")
    assert "A" not in context and "T" not in context, "条件为假,A 被跳过,只从 A 那里拿值也只在 A 之后跑的 T 也该跳过"
    assert context["B"]["text"] == "画面"


def test_T的数据和控制都只来自A_控制边照旧折掉_判法不变() -> None:
    saved, context = _save_and_run(_graph(with_b=False))
    assert ("A", "T") not in _pairs(saved, "control"), "只剩排先后一个作用的控制边该折掉"
    assert ("A", "T") in _pairs(saved, "data")
    assert "T" not in context, "折掉之后只剩来自 A 的数据边:A 被跳过,T 照样跳过"


def test_T另有条件的真出口_只排先后的控制边照旧折掉_由条件说了算() -> None:
    graph = _graph(with_b=True)
    #: 标题取分支外的 B(A 被跳过时正文是空的,通知照样发得出去)。
    next(node for node in graph["nodes"] if node["id"] == "T")["config"] = {"title": "{{B.text}}", "body": "{{A.text}}"}
    graph["edges"].append({"id": "e5", "source": "c", "target": "T", "source_handle": "false"})
    graph["edges"].append({"id": "e6", "source": "B", "target": "T"})
    saved, context = _save_and_run(graph)
    assert ("A", "T") not in _pairs(saved, "control") and ("B", "T") not in _pairs(saved, "control")
    assert ("c", "T") in _pairs(saved, "control")
    assert "T" in context, "条件为假,走「假」出口的 T 跑了 —— 排先后的边没把它拉回「A 或 B 跑了就跑」"
