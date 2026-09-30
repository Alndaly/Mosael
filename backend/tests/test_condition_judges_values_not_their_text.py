"""条件节点按值判,不按值写成的文字判。

- 「为空 / 不为空」此前先 `as_text` 再判:`[]` / `{}` 写成 JSON 是两个字符,不空 —— 「查询结果为空就
  走另一支」对一个空列表判成了「不为空」,正好反了。
- 「等于」比数字时按文字:上游算出来的 `30.0` 和手填的 `30` 永远不等。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client


def _judge(left, op: str, right="") -> bool:
    """真跑一遍:左边经数据边从开始节点绑进来(和接上游节点的输出同一条路,值保留原类型)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="判", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "check", "type": "condition", "config": {"left": "", "op": op, "right": right}},
        ],
        "edges": [{"id": "d1", "source": "start", "target": "check", "kind": "data",
                   "source_output": "value", "target_input": "left"}],
    }
    context, _ = execute_graph(graph, wf_id=wf_id, params={"value": left})
    return context["check"]["result"]


@pytest.mark.parametrize(("value", "empty"), [([], True), ({}, True), (None, True), ("  ", True),
                                              ([0], False), ({"a": 1}, False), ("x", False), (0, False)])
def test_为空按值的样子判(value, empty: bool) -> None:
    assert _judge(value, "empty") is empty
    assert _judge(value, "not_empty") is (not empty)


def test_等于_两边都是数就按数比() -> None:
    assert _judge(30.0, "equals", "30") is True
    assert _judge(30.0, "not_equals", "30") is False
    assert _judge("1e3", "equals", "1000") is True


def test_等于_不是数的照旧按文字比() -> None:
    assert _judge("abc", "equals", "abc") is True
    assert _judge(True, "equals", "true") is True, "布尔照 JSON 写成 true"
    assert _judge(True, "equals", "1") is False, "布尔不当数"
