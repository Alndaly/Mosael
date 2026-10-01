"""子工作流的输出是一份**契约**,没有"契约给不出东西时换一种形状"的退路。

## 现场

`call_workflow` 此前返回:

    result.get("output") or result.get("context") or {}

两个毛病叠在一起:

1. **`or` 判真假,不判有无。** 被调图**有**输出节点、而这次跑出来的具名输出恰好是空字典
   (条件分支没走到、上游返回空)时,`result.get("output")` 为假 → 掉进整份上下文。调用方拿到
   的是**完全不同的形状**:从"我声明的那几个名字"变成"被调图里每个节点 id 的全部产出"。
2. **退路那一份是被裁剪过的。** `context` 过了 `_trim_outputs`:顶层字符串超 2000 字截断并加
   `…`、列表只留 200 项、对象只留 100 个字段。于是一份长文案、一段 LLM 回答、一串 id 列表
   经这条退路传上去会**安静地少一截**。

裁剪的本意是给**人**看的快照(事件体积有上限),而它同时被当成了给机器用的数据源 ——
两个读者共用一份字段,而只有一个读者需要有界。

退路是明写的向后兼容分支,而本仓库的规矩是不写兼容、改形状带迁移(ADR-0006):
老数据由 `_migrate_called_workflows_declare_their_output` 补上输出节点。
"""

from __future__ import annotations

import inspect


from app.domain.workflows.executors import subworkflow


def test_没有退路了() -> None:
    """**读 AST,不读源码文本。**

    第一版直接在源码里搜 `result.get("context")` —— 而上面那段注释里正好引用了被删掉的旧代码
    作为说明,于是它打到了自己身上。这一轮第四次栽在"扫描面比判据宽"上了。
    """
    import ast

    tree = ast.parse(inspect.getsource(subworkflow.call_workflow).lstrip())
    returns = [node for node in ast.walk(tree) if isinstance(node, ast.Return)]
    for node in returns:
        assert not any(
            isinstance(inner, ast.BoolOp) and isinstance(inner.op, ast.Or)
            for inner in ast.walk(node)
        ), "返回里又出现了 `a or b` —— 那是判真假,不是判有无"
    compares = [node for node in ast.walk(tree) if isinstance(node, ast.Compare)]
    assert any(isinstance(node.ops[0], ast.NotIn) for node in compares), "不再判「有没有 output」了"


def _call(child_graph: dict) -> tuple[str, dict, str | None, str | None]:
    """真跑一遍:父流程 call_workflow 调子流程,**都走真的 run_workflow**。

    此前这两条用例把 wait_for_job / start_workflow_job 打了桩,喂进去一个手造的、缺 `output` 键的结果
    —— 而真实的 run_workflow **总会**写 `output`,于是「被调图没有输出节点」那句报错永远说不出口,
    桩把这件事盖住了。
    """
    import time

    from app.core.db import SessionLocal
    from app.db.models import Job, Workflow
    from app.domain.workflows import create_workflow
    from app.domain.workflows.engine import start_workflow_job
    from tests.util import fresh_client, user_id

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        child = create_workflow(db, workspace_id=ws, name="配音子流程", graph=child_graph, created_by=user_id())
        db.flush()
        parent = create_workflow(db, workspace_id=ws, name="父", graph={
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "call", "type": "call_workflow", "config": {"workflow_id": child.id}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "call"}],
        }, created_by=user_id())
        db.commit()
        job = start_workflow_job(db, db.get(Workflow, parent.id), created_by=user_id(), params={})
        db.commit()  # 测试是入口:任务在提交之后才派发(jobs.dispatch_job)
        job_id = job.id
    for _ in range(150):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                return job.status, job.result or {}, job.error, job.error_key
        time.sleep(0.1)
    raise AssertionError("工作流没跑完")


def test_空的具名输出仍然是具名输出_不掉进另一种形状() -> None:
    """这一条是 `or` 和 `in` 的全部区别:**有**输出节点、这次恰好没走到(条件为假),契约仍然成立。"""
    status, result, error, _ = _call({
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "check", "type": "condition", "config": {"left": "a", "op": "empty"}},
            {"id": "out", "type": "output", "config": {"values": {"greeting": "你好"}}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "check"},
            {"id": "e2", "source": "check", "target": "out", "source_handle": "true"},
        ],
    })
    assert status == "succeeded", error
    assert result["context"]["call"] == {"output": {}}, "空的具名输出掉进了另一种形状"


def test_被调图没有输出节点时说得出口() -> None:
    """报的是"加一个输出节点",而不是悄悄给一份空的数据。"""
    status, _, error, error_key = _call({
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "t", "type": "template", "config": {"template": "一段长文案"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "t"}],
    })
    assert status == "failed", "调用一张没有输出节点的工作流,静默拿到了 {}"
    assert error_key == "wfErr_calledWorkflowHasNoOutput"
    assert "配音子流程" in (error or ""), "报错里没说是哪一个工作流"


def test_输出节点不能放进循环体或子图() -> None:
    """放在体里它照样跑、产出却没人收 —— 看起来声明了输出,被调用时拿到的还是没有。"""
    from app.domain.workflows import validate_graph

    body = {"nodes": [{"id": "out", "type": "output", "config": {"values": {"x": "1"}}}], "edges": []}
    for container in ({"type": "subgraph", "config": {"body": body}},
                      {"type": "loop_foreach", "config": {"items": "a", "body": body}}):
        errors = validate_graph({
            "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "box", **container}],
            "edges": [{"id": "e1", "source": "start", "target": "box"}],
        })
        assert any("输出" in one for one in errors), errors


def test_迁移给被调用的旧图补上输出节点() -> None:
    """**不写兼容,旧数据用迁移**(ADR-0006)。补出来的正是老行为的显式版本:
    暴露的还是那些终端节点的产出,只是从此有名有姓、而且不再被裁剪。"""
    import json

    from sqlalchemy import text

    from app.core.db import SessionLocal, engine
    from app.db.migrations import _migrate_called_workflows_declare_their_output
    from app.db.models import Workflow
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        child = Workflow(workspace_id=ws, name="子", graph={
            "nodes": [{"id": "n1", "type": "llm", "config": {"prompt": "写一段"}}],
            "edges": [],
        })
        parent = Workflow(workspace_id=ws, name="父", graph={"nodes": [], "edges": []})
        db.add_all([child, parent])
        db.flush()
        parent.graph = {
            "nodes": [{"id": "c1", "type": "call_workflow", "config": {"workflow_id": child.id}}],
            "edges": [],
        }
        db.commit()
        child_id = child.id

    _migrate_called_workflows_declare_their_output()

    with engine.begin() as conn:
        raw = conn.execute(text("SELECT graph FROM workflows WHERE id = :id"), {"id": child_id}).scalar()
    graph = json.loads(raw) if isinstance(raw, str) else raw
    outputs = [node for node in graph["nodes"] if node["type"] == "output"]
    assert outputs, "被调用的旧图没有补上输出节点"
    values = outputs[0]["config"]["values"]
    assert values, "补出来的输出节点是空的 —— 那和没补一样"
    assert all(value.startswith("{{") for value in values.values())
