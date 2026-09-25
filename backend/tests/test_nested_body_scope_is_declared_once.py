"""内嵌子图(循环体 / subgraph)**体内看得见什么**,由节点自己声明一次(`body_scope`)。

三方此前各写各的:

- 执行器:遍历循环播 `loop` + `input`,条件循环只播 `loop`,子图只播 `input`;
- 后端校验:所有循环一律放行 `loop` 与 `input` —— 条件循环体里的 `{{input.x}}` 校验得过,
  运行时**安静地变成空串**;
- 画布就绪检查:循环和子图一律放行 `loop` 与 `input` —— 子图体里的 `{{loop.item}}` 画布说能跑,
  后端却拒绝。

而且体的校验(越出作用域、空体、体里有开始节点……)此前只在**执行器真跑到它时**才做:工作流
先占一个任务位、把循环之前的步骤全跑完(可能是好几次付费的 AI 调用),然后才死在循环上。
"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, Workflow
from app.domain.workflows import NESTED_BODY_TYPES, NODE_TYPES, WorkflowDomainError, create_workflow, validate_graph
from app.domain.workflows.engine import start_workflow_job
from tests.util import fresh_client

RATCHET = True


def _graph(container: str, body_template: str, **config) -> dict:
    body = {"nodes": [{"id": "say", "type": "template", "config": {"template": body_template}}], "edges": []}
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "before", "type": "template", "config": {"template": "循环之前的一步"}},
            {"id": "box", "type": container, "config": {"body": body, **config}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "before"},
            {"id": "e2", "source": "before", "target": "box"},
        ],
    }


def _saved(graph: dict) -> Workflow:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="体的作用域", graph=graph)
        db.expunge(workflow)
        return workflow


def _run(workflow: Workflow) -> tuple[str, dict, str | None]:
    with SessionLocal() as db:
        job_id = start_workflow_job(db, db.get(Workflow, workflow.id), created_by=None).id
    for _ in range(100):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                return job.status, job.result or {}, job.error
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def test_条件循环体里的_input_在启动前就被拒() -> None:
    """条件循环没有「逐项共享输入」这一格,执行器不播 `input`。此前校验照样放行,
    `{{input.who}}` 跑出来是 `x=` —— 没有报错,只有一段少了字的产出。"""
    workflow = _saved(_graph("loop_while", "x={{input.who}}", output="{{say.text}}"))
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        start_workflow_job(db, db.get(Workflow, workflow.id), created_by=None)
    assert "input" in str(caught.value) and "box" in str(caught.value)


def test_子图体里的_loop_在启动前就被拒() -> None:
    workflow = _saved(_graph("subgraph", "x={{loop.item}}", output="{{say.text}}"))
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        start_workflow_job(db, db.get(Workflow, workflow.id), created_by=None)
    assert "loop" in str(caught.value)


@pytest.mark.parametrize(
    "body_template",
    ["x={{start.who}}", "x={{before.text}}"],
    ids=["引用了开始节点", "引用了循环外的上游"],
)
def test_体里越出作用域的引用在启动前就被拒(body_template: str) -> None:
    """此前 start_workflow_job 放行,`before` 先跑完,循环才报错 —— 前面那几步白跑了。"""
    workflow = _saved(_graph("loop_foreach", body_template, items=["a"], output="{{say.text}}"))
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        start_workflow_job(db, db.get(Workflow, workflow.id), created_by=None)
    assert "循环外" in str(caught.value)
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.kind == "workflow").count() == 0, "被拒的工作流不该占一个任务位"


def test_空的循环体在启动前就被拒() -> None:
    graph = _graph("loop_foreach", "x", items=["a"])
    graph["nodes"][2]["config"].pop("body")
    assert any("循环体不能为空" in one and "box" in one for one in validate_graph(graph))
    # 保存照样放行:刚拖出来的循环节点还没有体,那是「还没配完」,不是错。
    assert validate_graph(graph, require_config=False) == []


@pytest.mark.parametrize(
    ("container", "body_template", "config", "expected"),
    [
        ("loop_foreach", "{{loop.index}}:{{loop.item}}/{{input.tag}}", {"items": ["a", "b"], "inputs": {"tag": "T"}, "output": "{{say.text}}"},
         {"results": ["0:a/T", "1:b/T"], "count": 2}),
        ("loop_while", "第{{loop.index}}轮", {"output": "{{say.text}}"}, {"results": ["第0轮"], "count": 1, "iterations": 1}),
        ("subgraph", "你好 {{input.who}}", {"inputs": {"who": "世界"}, "output": "{{say.text}}"}, {"output": "你好 世界"}),
    ],
)
def test_声明了的作用域运行时都拿得到值(container: str, body_template: str, config: dict, expected: dict) -> None:
    """声明说得出的名字,执行器就得真的播种它 —— `run_body` 在两者不一致时直接报编程错误。"""
    status, result, error = _run(_saved(_graph(container, body_template, **config)))
    assert status == "succeeded", error
    assert result["context"]["box"] == expected


def test_每种内嵌子图节点都声明了作用域() -> None:
    assert NESTED_BODY_TYPES == {"loop_foreach", "loop_while", "subgraph"}
    for name in NESTED_BODY_TYPES:
        scope = NODE_TYPES[name]["body_scope"]
        # 作用域名 → 这个名字底下有哪些字段。`*字段名` 表示「这个配置字段里的每个键」(和 start 的
        # `*params` 输出同一种写法):子图的 {{input.*}} 是用户自己在 inputs 里起的名字。
        assert isinstance(scope, dict) and scope, name
        for root, fields in scope.items():
            assert isinstance(root, str) and root, name
            assert isinstance(fields, list) and fields and all(isinstance(one, str) and one for one in fields), name
            for field in fields:
                if field.startswith("*"):
                    assert field[1:] in NODE_TYPES[name]["config"], f"{name}.{root} 的键来自一个不存在的配置字段"
        assert NODE_TYPES[name]["config"]["body"]["type"] == "graph", f"{name} 声明了作用域却没有体"


def test_作用域的字段随节点类型发到画布() -> None:
    """画布给体里的引用选择器列 {{loop.item}} 还是只列 {{loop.index}},读的就是这一格 ——
    此前前端按「是不是 subgraph」自己写了一份,条件循环体里也列出了它根本拿不到的 loop.item。"""
    rows = {row["type"]: row for row in fresh_client().get("/api/workflows/node-types").json()}
    assert rows["loop_while"]["body_scope"] == {"loop": ["index"]}
    assert rows["loop_foreach"]["body_scope"] == {"loop": ["item", "index"], "input": ["*inputs"]}
    assert rows["subgraph"]["body_scope"] == {"input": ["*inputs"]}
    assert rows["template"]["body_scope"] == {}


def test_条件循环体里的_loop_item_在启动前就被拒() -> None:
    """`loop` 这个名字条件循环有,但它底下只有 `index`。只认名字的话,`{{loop.item}}` 校验得过、
    运行时安静地变成空串 —— 和 `{{input.x}}` 那条是同一种失败。"""
    workflow = _saved(_graph("loop_while", "x={{loop.item}}", output="{{say.text}}"))
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        start_workflow_job(db, db.get(Workflow, workflow.id), created_by=None)
    assert "loop.item" in str(caught.value) and "box" in str(caught.value)
