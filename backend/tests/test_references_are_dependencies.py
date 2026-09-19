"""**引用即依赖**:一个节点 `{{…}}` 引用了谁,就要等谁落定。

此前"引用了谁"和"等谁跑完"是两件脱钩的事。引擎只按边调度,而规范化只会把「顶层字段、恰好
两段路径」的引用变成数据边 —— `{{分镜.json.shots}}`(三段)或嵌在循环 `inputs` 对象里的
`{{start.voice_id}}` 都不产生边。于是一个节点可能在它引用的节点跑完之前开始,取到空值。

CI 上就是这么红的:整片生成的中段测试里,循环的 `inputs.voice_id` 有时取到空串,三镜的口播
全没合成 —— 本地 12 次挂 4 次。测试本身没错,错在引擎。
"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import executors as registry
from app.domain.workflows import reference_dependencies, validate_graph
from tests.util import fresh_client


def _workflow_id() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def test_没有连线_只靠引用_也要等被引用的节点跑完(monkeypatch) -> None:
    from app.domain.workflows.engine import execute_graph

    def slow(db, workflow, config):
        time.sleep(0.1)  # 慢一点:不等的话,读的一方一定先跑
        return {"json": {"voice": {"id": "voice-1"}}}

    monkeypatch.setitem(registry._REGISTRY, "code", slow)
    monkeypatch.setitem(registry._REGISTRY, "template", lambda db, workflow, config: {"text": config["template"]})
    graph = {
        "nodes": [
            {"id": "slow", "type": "code", "config": {"code": "x"}},
            #: 三段路径、没有连线 —— 规范化不会给它补数据边。
            {"id": "reader", "type": "template", "config": {"template": "音色:{{slow.json.voice.id}}"}},
        ],
        "edges": [],
    }
    context, _ = execute_graph(graph, wf_id=_workflow_id(), entry_is_root=True)
    assert context["reader"] == {"text": "音色:voice-1"}


def test_嵌在对象字段里的引用也算() -> None:
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "loop", "type": "loop_foreach", "config": {
                "items": "{{plan.json.shots}}",
                "inputs": {"voice_id": "{{start.voice_id}}"},
                #: 循环体属于内层作用域:体里引用的 loop / input 不是这一层的节点。
                "body": {"nodes": [{"id": "inner", "type": "template", "config": {"template": "{{loop.item}}"}}], "edges": []},
            }},
            {"id": "plan", "type": "llm", "config": {}},
        ],
        "edges": [],
    }
    assert reference_dependencies(graph) == {"start": set(), "loop": {"plan", "start"}, "plan": set()}


def test_引用绕回自己时_保存就报环路() -> None:
    """A 连到 B,B 却引用 A 的下游 C… 这里简化成 A→B 连线、A 引用 B:此前能跑,只是 A 取到空值。"""
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "a", "type": "template", "config": {"template": "{{b.text}}"}},
            {"id": "b", "type": "template", "config": {"template": "x"}},
        ],
        "edges": [{"id": "e0", "source": "start", "target": "a"}, {"id": "e1", "source": "a", "target": "b"}],
    }
    assert any("环路" in error for error in validate_graph(graph))


@pytest.mark.parametrize("config", [{"template": "{{reader.text}}"}, {"template": "自己:{{self.text}}"}])
def test_引用自己或不存在的节点不算依赖(config) -> None:
    graph = {"nodes": [{"id": "self", "type": "template", "config": config}], "edges": []}
    assert reference_dependencies(graph) == {"self": set()}
