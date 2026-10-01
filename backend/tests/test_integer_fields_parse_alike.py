"""整数格一个判法(common.whole_number):`"10.0"` 是 10,`"10.5"` 报「哪一格必须是整数」。

## 现场

几处整数格各写各的:新建成片项目的宽高 `int(… or 1920)`(`"1920.0"` 报笼统的「必须是数字」,填 0 悄悄换成
1920);笔记检索的 limit / offset 自己判(`"10.0"` 被判成不是整数);循环的 concurrency `int(float(…))`
(2.5 悄悄截成 2)。数字格插值、绑定之后常常是 `"10.0"`(上游算出来的数)。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client


def _run(node: dict) -> dict:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="整数", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        workflow_id = workflow.id
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, node],
             "edges": [{"id": "e1", "source": "start", "target": node["id"]}]}
    context, _ = execute_graph(graph, wf_id=workflow_id)
    return context[node["id"]]


def _loop(concurrency: object) -> dict:
    return {"id": "n", "type": "loop_foreach", "config": {
        "items": ["a", "b"], "concurrency": concurrency, "output": "{{t.text}}",
        "body": {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.item}}"}}], "edges": []},
    }}


def test_宽高写成小数形式的整数照收_带小数的说是哪一格_填0不再悄悄换成默认() -> None:
    made = _run({"id": "n", "type": "project_sequence_create", "config": {"name": "片子", "width": "1080.0", "height": 1920}})
    assert made["sequence_id"]
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"id": "n", "type": "project_sequence_create", "config": {"name": "片子", "width": "1080.5"}})
    assert caught.value.key == "wfErr_mustBeInteger"
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"id": "n", "type": "project_sequence_create", "config": {"name": "片子", "width": 0}})
    assert caught.value.key == "wfErr_canvasSizeRange"


def test_笔记检索的条数写成小数形式的整数照收_越界说范围() -> None:
    assert _run({"id": "n", "type": "note_search", "config": {"query": "x", "limit": "10.0"}})["count"] == 0
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"id": "n", "type": "note_search", "config": {"query": "x", "limit": "10.5"}})
    assert caught.value.key == "wfErr_mustBeInteger"
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"id": "n", "type": "note_search", "config": {"query": "x", "limit": 99}})
    assert caught.value.key == "wfErr_integerRange"


def test_循环并发数_小数形式的整数照收_带小数的不再悄悄截断() -> None:
    assert _run(_loop("2.0"))["results"] == ["a", "b"]
    with pytest.raises(WorkflowDomainError) as caught:
        _run(_loop("2.5"))
    assert caught.value.key == "wfErr_mustBeInteger"
