"""插件节点**跑得起来**,而不只是校验得过。

`plugin_node_types` 存在的全部意义是让插件节点"和内置节点没有区别"。校验那一侧早就带上了
`extra_types`(见 test_plugin_nodes_are_known_everywhere),可执行那一侧还有只认内置
`NODE_TYPES` 的地方 —— 那些地方不报"未知类型",而是在别的步骤上把整条工作流带崩。

这里不装真插件:插件从哪来(清单、实例、凭据)不是这条测试关心的事,它只关心"一个插件节点
类型存在时,引擎怎么对待它"。所以把 `plugin_node_types` 换成返回一个现成的节点声明,执行器
换成一个回声。
"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent
from app.domain.workflows import create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client

ECHO = "plugin.demo.echo"


@pytest.fixture
def echo_plugin(monkeypatch):
    from app.domain.plugins.nodes import node_meta

    meta = node_meta({"name": "echo", "label": "回声", "input_schema": {"properties": {"q": {"type": "string"}}}})
    monkeypatch.setattr("app.domain.plugins.nodes.plugin_node_types", lambda db, user_id=None: {ECHO: meta})

    def echo(db, workflow, config):
        return {"output": f"echo {config.get('q')}"}

    monkeypatch.setattr(
        "app.domain.workflows.engine.get_executor", lambda kind: echo if kind == ECHO else get_executor(kind)
    )


def _run(graph: dict) -> tuple[str, dict, str | None, str]:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="插件节点", graph=graph)
        job_id = start_workflow_job(db, workflow, created_by=None).id
    for _ in range(100):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                return job.status, job.result or {}, job.error, job_id
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def test_没起名字的插件节点照样能跑(echo_plugin) -> None:
    """智能体加节点时**不写名字**(见 graph_ops.add_node),显示时回退到节点类型的 label。

    引擎取这个 label 时只查了内置的 NODE_TYPES —— 插件节点在那儿查不到,KeyError 一抛,
    整条工作流失败,报错是一句 `'plugin.demo.echo'`。节点本身一行都没跑。
    """
    status, result, error, job_id = _run(
        {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "echo", "type": ECHO, "config": {"q": "你好"}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "echo"}],
        }
    )
    assert status == "succeeded", error
    assert result["context"]["echo"] == {"output": "echo 你好"}
    with SessionLocal() as db:
        started = [
            event.payload
            for event in db.query(TaskEvent).filter(TaskEvent.job_id == job_id, TaskEvent.type == "workflow.node.started")
            if event.payload.get("node_id") == "echo"
        ]
    assert started and started[0]["name"] == "回声", "事件里的名字该是插件声明的 label"


@pytest.mark.parametrize(
    ("container", "extra"),
    [
        ("loop_foreach", {"items": ["a", "b"], "output": "{{echo.output}}"}),
        ("subgraph", {"output": "{{echo.output}}"}),
    ],
)
def test_循环体和子图里的插件节点照样能跑(echo_plugin, container: str, extra: dict) -> None:
    """体此前由执行器在运行时**再校验一遍**,而那一遍不带插件节点类型 —— 体里的插件节点一律
    被判成「来自插件 demo 的工具 echo,该插件未安装或未启用」。插件明明装着,顶层的同一个节点
    也跑得好好的;用户会照着这句话去插件页找问题。"""
    body = {"nodes": [{"id": "echo", "type": ECHO, "config": {"q": "{{loop.item}}" if container == "loop_foreach" else "内"}}], "edges": []}
    status, result, error, _ = _run(
        {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "box", "type": container, "config": {"body": body, **extra}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "box"}],
        }
    )
    assert status == "succeeded", error
    produced = result["context"]["box"]
    assert produced == ({"results": ["echo a", "echo b"], "count": 2} if container == "loop_foreach" else {"output": "echo 内"})
