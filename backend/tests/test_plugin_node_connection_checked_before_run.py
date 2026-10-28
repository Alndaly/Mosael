"""插件节点落到哪条连接,开跑前和执行时是**同一条**规矩(plugins.nodes.resolve_instance)。

此前开跑前只看节点类型:节点上存着别人的(或已经删掉的)连接 id 时放行,跑到这一步报「选的连接已不可用」——
前面的节点钱已经花了;画板上的工具对同一种情况却是「当作没选、按他自己的连接挑」。现在:

- 存着的是别人的 / 删掉的连接:当作没选,他只有一条就用它(和画板一致),照常跑完;
- 他自己选的那条停用了、或者有好几条却没选:开跑前就报,不建任务。

装一个真的进程插件、走 start_workflow_job 跑,不把 resolve_instance / 执行器换掉。
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, PluginInstance, PluginPackage
from app.domain.plugins.tools import refresh_tools
from app.domain.workflows import create_workflow
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.engine import start_workflow_job
from tests.util import fresh_client, second_client, user_id

PACKAGE = "dev.test.echo"
ENTRY = """
    import json, sys
    request = json.loads(sys.stdin.read())
    print(json.dumps({"ok": True, "output": {"said": request["input"].get("text", "")}}))
"""


def _package(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "echo"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    manifest = {"id": PACKAGE, "name": "回声", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": [{
                    "name": "say", "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                    "node": {"outputs": ["said"]}}]},
                "_path": str(plugin_dir)}
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="回声", version="0.1.0", manifest=manifest))
        db.commit()


def _connection(owner: str, name: str) -> str:
    with SessionLocal() as db:
        instance = PluginInstance(package_id=PACKAGE, name=name, enabled=True, owner_user_id=owner)
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()
        return instance.id


def _start(ws: str, instance_id: str, *, in_loop: bool = False) -> str:
    say = {"id": "s", "type": f"plugin.{PACKAGE}.say", "config": {"text": "嗨", "instance_id": instance_id}}
    if in_loop:
        say = {"id": "loop", "type": "loop_foreach",
               "config": {"items": '["a"]', "body": {"nodes": [say], "edges": []}}}
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, say],
             "edges": [{"id": "e1", "source": "start", "target": say["id"]}]}
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="回声", graph=graph, created_by=user_id())
        db.commit()
        job = start_workflow_job(db, workflow, created_by=user_id())
        #: 测试就是入口:任务在起它的那次事务提交之后才派发(jobs.dispatch_job)。
        db.commit()
        return job.id


def _settled(job_id: str) -> Job:
    for _ in range(200):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                return job
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def _jobs() -> int:
    with SessionLocal() as db:
        return db.query(Job).filter(Job.kind == "workflow").count()


def test_节点上存着别人的连接_当作没选_用他自己唯一的那条跑完(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    second_client("mate")
    _package(tmp_path)
    theirs = _connection(user_id("mate"), "别人的")
    _connection(user_id(), "我的")

    job = _settled(_start(ws, theirs))
    assert job.status == "succeeded", job.error
    assert job.result["context"]["s"]["said"] == "嗨"


def test_节点上存着已经删掉的连接_当作没选(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _package(tmp_path)
    _connection(user_id(), "我的")

    job = _settled(_start(ws, "deleted-connection-id"))
    assert job.status == "succeeded", job.error


def test_他自己选的那条停用了_开跑前就报_不建任务(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _package(tmp_path)
    mine = _connection(user_id(), "停用的")
    _connection(user_id(), "还能用的")
    with SessionLocal() as db:
        db.get(PluginInstance, mine).enabled = False
        db.commit()

    before = _jobs()
    with pytest.raises(WorkflowDomainError) as raised:
        _start(ws, mine)
    assert raised.value.key == "pluginErr_instanceGone"
    assert _jobs() == before, "开跑前就该拦下,不建任务"


def test_有好几条连接却没选_开跑前就报_循环体里的也算(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    second_client("mate")
    _package(tmp_path)
    theirs = _connection(user_id("mate"), "别人的")
    _connection(user_id(), "B 站")
    _connection(user_id(), "抖音")

    before = _jobs()
    with pytest.raises(WorkflowDomainError) as raised:
        _start(ws, theirs)  # 别人的 = 没选;他有两条,不替他猜
    assert raised.value.key == "pluginErr_manyInstances"
    with pytest.raises(WorkflowDomainError) as nested:
        _start(ws, "", in_loop=True)
    assert nested.value.key == "pluginErr_manyInstances"
    assert _jobs() == before


def test_经运行接口_好几条连接没选_回的是能落到那个节点的失败说明(tmp_path) -> None:
    """点运行被拦,界面要能说「去哪儿、改什么」:422 带上一步一步的提示和是哪个节点(循环体里就带上外层)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _package(tmp_path)
    _connection(user_id(), "B 站")
    _connection(user_id(), "抖音")
    say = {"id": "s", "type": f"plugin.{PACKAGE}.say", "config": {"text": "嗨", "instance_id": ""}}
    loop = {"id": "loop", "type": "loop_foreach", "config": {"items": '["a"]', "body": {"nodes": [say], "edges": []}}}
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}, loop],
             "edges": [{"id": "e1", "source": "start", "target": "loop"}]}
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "回声", "graph": graph}).json()

    before = _jobs()
    refused = client.post(f"/api/workflows/{saved['id']}/run", json={"params": {}},
                          headers={"Accept-Language": "zh-CN"})
    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "workflow_run_refused"
    assert detail["node_id"] == "s" and detail["scope"] == ["loop"] and detail["field"] == "instance_id", detail
    steps = [step["text"] for step in detail["error_hint"]["steps"]]
    assert steps == ["打开这个节点的「高级选项」,在「连接」里选这次要用的那一条"], detail
    assert detail["message"] and detail["error_summary"], detail
    assert _jobs() == before
