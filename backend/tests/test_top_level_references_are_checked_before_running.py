"""顶层的 `{{节点.字段}}` 在运行前校验:根节点要存在,开始节点的字段要么声明了、要么这次给了。

画布会标出失效引用,可定时任务、智能体、call_workflow 触发的运行不经过画布 —— 拼错的
`{{scirpt.text}}`、调用方少传的 `{{start.topic}}` 运行时静默插值成空串,下游拿着空提示词去付费。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError, create_workflow, validate_graph
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.graph_rules import with_run_params
from tests.util import fresh_client, user_id


def _graph(template: str, params: dict | None = None) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": params or {}}},
            {"id": "script", "type": "template", "config": {"template": "稿子"}},
            {"id": "t", "type": "template", "config": {"template": template}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "script"}, {"id": "e2", "source": "script", "target": "t"}],
    }


def test_引用不存在的节点_运行前就报() -> None:
    errors = validate_graph(_graph("{{scirpt.text}}"))
    assert errors == ["「文本模板(t)」引用了不存在的节点:scirpt · text"], errors


def test_保存时不拦_删了一个节点还没改引用也存得下() -> None:
    assert validate_graph(_graph("{{scirpt.text}}"), require_config=False, allow_missing_start=True) == []


def test_容器的体内字段不按顶层判() -> None:
    """循环的 output 引用体里的节点,那不是顶层引用。"""
    graph = _graph("{{script.text}}")
    graph["nodes"].append({
        "id": "each", "type": "loop_foreach",
        "config": {"items": "{{script.text}}", "output": "{{inner.text}}",
                   "body": {"nodes": [{"id": "inner", "type": "template", "config": {"template": "{{loop.item}}"}}],
                            "edges": []}},
    })
    graph["edges"].append({"id": "e3", "source": "script", "target": "each"})
    assert validate_graph(graph) == []


def _start_errors(graph: dict, params: dict) -> list[str]:
    """运行前校验看到的是**这一次运行**的图:开始节点叠上本次参数(和 start_workflow_job 同一条路)。"""
    return [one for one in validate_graph(with_run_params(graph, params)) if "引用的开始参数不存在" in one]


def test_开始节点的参数_声明了或这次给了才算() -> None:
    graph = _graph("{{start.topic}} {{script.text}}")
    missing = _start_errors(graph, {})
    assert missing == ["「文本模板(t)」引用的开始参数不存在:start · topic。在开始节点的参数里声明它,或运行时传进来"]
    assert _start_errors(graph, {"topic": "猫"}) == []
    assert _start_errors(_graph("{{start.topic}}", params={"topic": ""}), {}) == []


def test_从开始节点拉出的数据边也要有那个参数() -> None:
    graph = _graph("")
    graph["edges"].append({"id": "d1", "source": "start", "target": "t", "kind": "data",
                           "source_output": "topic", "target_input": "template"})
    #: 算在数据边的目标节点头上。
    assert _start_errors(graph, {}) == [
        "「文本模板(t)」引用的开始参数不存在:start · topic。在开始节点的参数里声明它,或运行时传进来"
    ]
    assert _start_errors(graph, {"topic": "猫"}) == []


def test_启动任务时就拦下_不建任务() -> None:
    """定时任务、智能体、call_workflow 都从 start_workflow_job 进来 —— 在这里拦,就一处都不漏。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="少传一个", graph=_graph("{{start.topic}}"),
                                   created_by=user_id())
        db.commit()
        try:
            start_workflow_job(db, db.get(Workflow, workflow.id), created_by=user_id(), params={})
        except WorkflowDomainError as exc:
            assert str(exc) == "「文本模板(t)」引用的开始参数不存在:start · topic。在开始节点的参数里声明它,或运行时传进来"
        else:
            raise AssertionError("少传的参数没拦下来")
