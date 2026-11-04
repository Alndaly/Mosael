"""循环体读得到上一轮交出的东西(`loop.previous`)。

逐段续写视频这类活,下一段要接着上一段做:此前循环体只看得到 `loop.item` / `loop.index`,上一轮的产物拿不到,
这种图根本搭不出来。第一轮读 `previous_initial`。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.graph_rules import validate_graph
from tests.util import fresh_client


def _run(loop: dict) -> dict:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="循环", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "L", **loop}],
             "edges": [{"id": "e1", "source": "start", "target": "L"}]}
    context, _ = execute_graph(graph, wf_id=wf_id, params={})
    return context["L"]


CHAIN = {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.previous}}{{loop.item}}"}}], "edges": []}


def test_遍历循环_每一轮接着上一轮_第一轮读初值() -> None:
    out = _run({"type": "loop_foreach", "config": {
        "items": "甲\n乙\n丙", "body": CHAIN, "output": "{{t.text}}", "previous_initial": "起",
    }})
    assert out["results"] == ["起甲", "起甲乙", "起甲乙丙"]


def test_条件循环_也读得到上一轮() -> None:
    body = {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.previous}}+"}}], "edges": []}
    out = _run({"type": "loop_while", "config": {
        "body": body, "output": "{{t.text}}", "condition": "yes", "max_iterations": 3, "previous_initial": "0",
    }})
    assert out["results"] == ["0+", "0++", "0+++"]


def test_不写输出时_结果里不一轮套一轮() -> None:
    body = {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.previous.t.text}}{{loop.item}}"}}], "edges": []}
    out = _run({"type": "loop_foreach", "config": {"items": "甲\n乙\n丙", "body": body}})
    assert out["results"][2]["t"]["text"] == "甲乙丙"
    assert all("previous" not in one["loop"] for one in out["results"])


def test_跳过的一项什么都没交_下一轮接着最后交出来的() -> None:
    body = {"nodes": [
        {"id": "wait", "type": "delay", "config": {"seconds": "{{loop.item}}"}},
        {"id": "t", "type": "template", "config": {"template": "{{loop.previous}}{{loop.item}}"}},
    ], "edges": [{"id": "e", "source": "wait", "target": "t"}]}
    out = _run({"type": "loop_foreach", "config": {
        "items": "0\n坏\n0", "body": body, "output": "{{t.text}}", "on_item_error": "skip",
    }})
    assert out["failed"] == [2]
    assert out["results"] == ["0", "00"]


def test_同时跑几项时读上一轮_开跑前就拒() -> None:
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "L", "type": "loop_foreach", "config": {
        "items": "甲\n乙", "body": CHAIN, "concurrency": 2,
    }}], "edges": [{"id": "e1", "source": "start", "target": "L"}]}
    assert any("一项一项" in one for one in validate_graph(graph))


def test_并发数写成引用时_运行时再拒() -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _run({"type": "loop_foreach", "config": {"items": "甲\n乙", "body": CHAIN, "concurrency": "2"}})
    assert caught.value.key == "wfErr_loopPreviousNeedsOrder"
