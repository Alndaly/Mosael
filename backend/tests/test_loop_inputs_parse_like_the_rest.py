"""循环的两格输入按它们声明的样子解析,不悄悄换成别的。

- 遍历循环的 items 是一段 JSON 数组文本(LLM 的 text 输出)时,此前按行拆:排好版的数组被拆成
  `[`、`  "第一镜",`、`]` 几项,每一项都去跑了一遍循环体。现在和 common.text_lines 同一个顺序:先 JSON,后按行。
- 条件循环的「最多几轮」填 0(`or 50`)或 "10.0"(`int()` 抛错被吞)都悄悄变成 50 轮。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client


def _run(loop: dict, params: dict | None = None) -> dict:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="循环", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "L", **loop}],
        "edges": [{"id": "d1", "source": "start", "target": "L", "kind": "data",
                   "source_output": "items", "target_input": "items"}] if params else
                 [{"id": "e1", "source": "start", "target": "L"}],
    }
    context, _ = execute_graph(graph, wf_id=wf_id, params=params or {})
    return context["L"]


BODY = {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.item}}"}}], "edges": []}


def test_items_是一段排好版的_JSON_数组文本() -> None:
    reply = '[\n  "第一镜",\n  "第二镜"\n]'
    out = _run({"type": "loop_foreach", "config": {"items": "", "body": BODY, "output": "{{t.text}}"}},
               params={"items": reply})
    assert out["results"] == ["第一镜", "第二镜"]


def test_items_是一个_JSON_对象_报错而不是按行拆() -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"type": "loop_foreach", "config": {"items": "", "body": BODY}}, params={"items": '{"a": 1}'})
    assert caught.value.key == "wfErr_loopItems"


def test_items_是多行文本_照旧按行拆() -> None:
    out = _run({"type": "loop_foreach", "config": {"items": "甲\n\n乙", "body": BODY, "output": "{{t.text}}"}})
    assert out["results"] == ["甲", "乙"]


WHILE_BODY = {"nodes": [{"id": "t", "type": "template", "config": {"template": "go"}}], "edges": []}


def test_最多几轮_写成小数形式的整数照样认() -> None:
    out = _run({"type": "loop_while", "config": {"body": WHILE_BODY, "condition": "{{t.text}}", "max_iterations": "3.0"}})
    assert out["iterations"] == 3, "填了 3.0,跑的却是缺省的 50 轮"


@pytest.mark.parametrize(("value", "key"), [(0, "wfErr_belowMin"), ("2.5", "wfErr_mustBeInteger")])
def test_最多几轮_不合法就报错_不悄悄回退(value, key: str) -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"type": "loop_while", "config": {"body": WHILE_BODY, "condition": "{{t.text}}", "max_iterations": value}})
    assert caught.value.key == key
