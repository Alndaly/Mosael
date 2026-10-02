"""规范化折掉多余的控制边,不许改变「谁该跑」。

## 现场

规范化把精确引用 `{{A.text}}` 升级成数据边之后,会把同一对节点间无 handle 的控制边当多余的折掉 —— 数据边本身
也排先后。可引擎判「该不该跑」时,有控制边只看控制边,只有数据边时看数据边(任一来源跑了就跑)。T 的控制边只来自
条件分支里的 A、另有一条数据边来自分支外的 B 时,折掉 A→T 就把「A 跑了才跑」改成了「A 或 B 跑了就跑」:
条件为假、A 被跳过,T 照样拿着空的 A.text 跑了。

修法:T 另有带路由语义的控制边(条件的「真」出口)时,只排先后的那几条照旧折掉、由路由边说了算(官方模板靠
这个:「这一拍有画外音才放音轨」);没有路由边时,只在数据边的来源恰好就是控制边的来源时折。

第二处同一类:T 另有一条**不带数据**的普通控制边时,「不是只排先后」被当成了「带路由」,带数据的那条照样被折掉,
T 只剩那一条普通边说了算 —— 它没跑,T 就跟着不跑(出镜版带货口播收尾为空时字幕、导出整段跳过)。
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


def test_T另有一条不带数据的普通控制边_带数据的那条不折_那一条没跑T照样跑() -> None:
    """T 的控制边一条来自分支里的 A(不带数据)、一条来自分支外的 B(另有数据边)。作者画的是「A 或 B 跑了就跑」,
    折掉 B→T 就只剩 A→T:A 被跳过,T 也跟着跳过 —— 出镜版带货口播收尾那句是空的时,字幕、导出、交付就是这样整段没了。
    「不是只排先后」不等于「带路由」:A→T 没写 handle、A 也不是条件节点。"""
    graph = _graph(with_b=True)
    next(node for node in graph["nodes"] if node["id"] == "T")["config"] = {"title": "{{B.text}}", "body": "固定的正文"}
    graph["edges"].append({"id": "e5", "source": "B", "target": "T"})
    saved, context = _save_and_run(graph)
    assert {("A", "T"), ("B", "T")} <= _pairs(saved, "control"), "折掉 B→T,T 就变成「A 跑了才跑」"
    assert ("B", "T") in _pairs(saved, "data")
    assert "A" not in context, "条件为假,A 被跳过"
    assert context["T"]["sent"], "B 跑了,T 照样跑"


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
