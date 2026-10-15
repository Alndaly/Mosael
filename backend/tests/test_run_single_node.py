"""工作流「单跑一个节点」(以某节点为目标的子集运行)。

方案 A(后端支持):跑目标节点 + 它的 waits_for 传递闭包,到目标即停,**下游一律不跑**
(省算力/省钱)。闭包 = 数据边 + 控制边 + `{{A.x}}` 引用,即引擎现成的依赖口径
(见 engine.run_graph 的 waits_for 组装、graph_rules.target_dependency_closure)。

- 闭包外节点「不在本次运行」:不执行、不计入进度 total、不算失败,也不会因为它们缺配置
  /缺连接被预检拦下。
- 闭包内仍按拓扑序 + 依赖并行 + 条件分支活跃逻辑跑;闭包内无闭包依赖的节点作入口
  (等价 entry_is_root 语义)。
- 第一版只支持最外层(根作用域)节点:目标在循环体/子图体里 → 后端拒绝,说清楚在哪。
- 运行历史标注「部分运行(目标:节点名)」:载荷里多 `target_node_id` / `target_node_name`
  两格,不改正文 schema。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import TaskEvent, Workspace, Workflow
from app.domain.workflows import WorkflowDomainError, engine as wf_engine
from tests.util import fresh_client, wait_settled


def _workflow_id() -> str:
    """直调 run_graph 需要一个真实的工作流行(run_node 会按 wf_id 取它),图内容无所谓。"""
    with SessionLocal() as db:
        ws = Workspace(name="单跑测试")
        db.add(ws)
        db.flush()
        workflow = Workflow(workspace_id=ws.id, name="单跑", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _count_llm(monkeypatch) -> list[str]:
    """LLM 执行器桩:计数(零调用就是「下游没跑、钱没花」),其余类型走真注册表。"""
    real = wf_engine.get_executor
    calls: list[str] = []

    def fake(node_type: str):
        if node_type == "llm":
            def llm_executor(_db, _wf, _config):
                calls.append("llm")
                return {"text": "不该出现的产出"}

            return llm_executor
        return real(node_type)

    monkeypatch.setattr(wf_engine, "get_executor", fake)
    return calls


def _linear_graph() -> dict:
    """start → up → target → expensive(LLM,花钱)。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "up", "type": "template", "config": {"template": "上游产物"}},
            {"id": "target", "type": "template", "config": {"template": "目标:{{up.text}}"}},
            {"id": "expensive", "type": "llm", "config": {"prompt": "写一首诗"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "up"},
            {"id": "e2", "source": "up", "target": "target"},
            {"id": "e3", "source": "target", "target": "expensive"},
        ],
    }


def test_单跑目标_只执行闭包_下游执行器零调用(monkeypatch) -> None:
    llm_calls = _count_llm(monkeypatch)
    run = wf_engine.run_graph(_linear_graph(), wf_id=_workflow_id(), target_node="target")

    assert run.error is None
    assert not run.cancelled
    assert run.context["up"]["text"] == "上游产物", "闭包内的上游要跑"
    assert run.context["target"]["text"] == "目标:上游产物", "目标自身的产出要在"
    assert "expensive" not in run.context, "下游(闭包外)当作「不在本次运行」"
    assert llm_calls == [], "下游 LLM 一次都不能调 —— 这是省钱的那一半"


def test_单跑_闭包外节点不执行也不算失败(monkeypatch) -> None:
    """闭包外放一个**会跑挂**的节点:整段运行照样成功 —— 它不在本次运行里,不算失败。"""
    graph = _linear_graph()
    graph["nodes"].append({"id": "broken", "type": "template", "config": {"template": ""}})
    graph["nodes"].append({"id": "poison", "type": "llm", "config": {"prompt": ""}})
    run = wf_engine.run_graph(graph, wf_id=_workflow_id(), target_node="target")

    assert run.error is None, "闭包外缺配置的节点不该让这次运行失败"
    assert "poison" not in run.context
    assert run.context["target"]["text"] == "目标:上游产物"


def test_闭包覆盖数据边_控制边和引用三种依赖(monkeypatch) -> None:
    """target 的闭包要同时收进:数据边来源(src_data)、控制边来源(pre)、`{{…}}` 引用(src_ref)。"""
    llm_calls = _count_llm(monkeypatch)
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "src_data", "type": "template", "config": {"template": "数据边值"}},
            {"id": "src_ref", "type": "template", "config": {"template": "引用值"}},
            {"id": "pre", "type": "template", "config": {"template": "预:{{src_ref.text}}"}},
            {"id": "target", "type": "template", "config": {"template": ""}},
            {"id": "expensive", "type": "llm", "config": {"prompt": "写一首诗"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "src_data"},
            {"id": "e2", "source": "start", "target": "pre"},
            # 数据边:src_data.text → target.template(字面量留空,由边供值)。
            {"id": "d1", "source": "src_data", "target": "target", "kind": "data",
             "source_output": "text", "target_input": "template"},
            # 控制边:pre 跑完才轮到 target(也决定 target 该不该跑)。
            {"id": "e3", "source": "pre", "target": "target"},
            {"id": "e4", "source": "target", "target": "expensive"},
        ],
    }
    run = wf_engine.run_graph(graph, wf_id=_workflow_id(), target_node="target")

    assert run.error is None
    assert run.context["pre"]["text"] == "预:引用值", "{{…}} 引用来源要进闭包、要先跑"
    assert run.context["target"]["text"] == "数据边值", "数据边来源要进闭包、值要绑上"
    assert "expensive" not in run.context
    assert llm_calls == []


def test_闭包内无闭包依赖的节点作入口(monkeypatch) -> None:
    """目标不依赖 start 时,start 不在闭包里;只靠 `{{…}}` 挂着的上游作为入口跑起来。"""
    llm_calls = _count_llm(monkeypatch)
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "lonely", "type": "template", "config": {"template": "悬空的,不在闭包"}},
            {"id": "a", "type": "template", "config": {"template": "入口上游"}},
            {"id": "target", "type": "template", "config": {"template": "目标:{{a.text}}"}},
        ],
        "edges": [],
    }
    run = wf_engine.run_graph(graph, wf_id=_workflow_id(), target_node="target")

    assert run.error is None
    assert run.context["a"]["text"] == "入口上游", "无闭包内依赖的节点作入口(等价 entry_is_root)"
    assert run.context["target"]["text"] == "目标:入口上游"
    assert "start" not in run.context, "start 不在闭包里 —— 不执行"
    assert "lonely" not in run.context, "闭包外的孤立节点不执行"
    assert llm_calls == []


def test_目标在循环体或子图里_直接调引擎也报清楚的错() -> None:
    body = {"nodes": [{"id": "inner", "type": "template", "config": {"template": "体"}}], "edges": []}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": [1], "body": body, "output": ""}},
            {"id": "sub", "type": "subgraph", "config": {"inputs": {}, "body": body}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    }
    with pytest.raises(WorkflowDomainError, match="在循环体或子图里"):
        wf_engine.run_graph(graph, wf_id=_workflow_id(), target_node="inner")
    with pytest.raises(WorkflowDomainError, match="不在这张图里"):
        wf_engine.run_graph(graph, wf_id=_workflow_id(), target_node="ghost")


def _make_workflow(client, graph: dict) -> str:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "单跑", "graph": graph})
    assert workflow.status_code == 200, workflow.text
    return workflow.json()["id"]


def test_API带target_node_id_部分运行_历史有标注(monkeypatch) -> None:
    llm_calls = _count_llm(monkeypatch)
    client = fresh_client()
    workflow_id = _make_workflow(client, _linear_graph())

    run = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}, "target_node_id": "target"})
    assert run.status_code == 200, run.text
    job_id = run.json()["id"]
    assert wait_settled(client, job_id) == "succeeded"

    job = client.get(f"/api/jobs/{job_id}").json()
    context = job["result"]["context"]
    assert context["target"]["text"] == "目标:上游产物"
    assert "expensive" not in context, "下游不在这次运行里"
    assert job["payload"]["target_node_id"] == "target", "运行历史据此标注「部分运行」"
    assert job["payload"]["target_node_name"], "标注里带节点名"
    assert job["progress"] == 1.0, "进度 total 只算闭包内节点"
    assert llm_calls == [], "下游 LLM 的 HTTP 一发都没出"

    with SessionLocal() as db:
        events = db.query(TaskEvent).filter(TaskEvent.job_id == job_id).all()
    touched = {e.payload["node_id"] for e in events if e.type in (
        "workflow.node.started", "workflow.node.finished", "workflow.node.skipped")}
    assert touched == {"start", "up", "target"}, "闭包外的节点连事件都不发"


def test_API单跑_闭包外的坏节点不拦_但全量运行被拦(monkeypatch) -> None:
    """图里有一个缺必填的 LLM(闭包外):单跑 target 照常开始;不带 target 的整跑被同一个预检拦下。"""
    llm_calls = _count_llm(monkeypatch)
    graph = _linear_graph()
    graph["nodes"].append({"id": "broken", "type": "llm", "config": {}})  # 缺必填提示词,孤立
    client = fresh_client()
    workflow_id = _make_workflow(client, graph)

    full = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
    assert full.status_code == 422, "整跑照旧被预检拦下(行为不回退)"
    assert full.json()["detail"]["code"] == "workflow_run_refused"

    single = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}, "target_node_id": "target"})
    assert single.status_code == 200, single.text
    assert wait_settled(client, single.json()["id"]) == "succeeded"
    assert llm_calls == []


def test_API目标在循环体或子图里_422说清楚() -> None:
    body = {"nodes": [{"id": "inner", "type": "template", "config": {"template": "体"}}], "edges": []}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": [1], "body": body, "output": ""}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    }
    client = fresh_client()
    workflow_id = _make_workflow(client, graph)

    refused = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}, "target_node_id": "inner"})
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert detail["code"] == "workflow_run_refused"
    assert "循环体或子图" in detail["message"]

    missing = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}, "target_node_id": "ghost"})
    assert missing.status_code == 422
    assert "不在这张图里" in missing.json()["detail"]["message"]
