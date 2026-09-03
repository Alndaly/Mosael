from __future__ import annotations

import time

import httpx
import pytest

from app.core.db import SessionLocal
from app.db.models import Job, ProviderProfile, TaskEvent, Workflow
from app.domain.workflows import (
    NODE_TYPES,
    WorkflowDomainError,
    create_workflow,
    default_graph,
    interpolate,
    topo_order,
    update_workflow,
    validate_graph,
)
from tests.util import acting_as, add_provider, fresh_client


def _install_llm_transport(monkeypatch, module, handler) -> None:
    """LLM 节点的 HTTP 桩。打在 RetryingClient 的传输上 —— 重试统一在传输层做,
    换掉 httpx.post 既拦不住它,也把重试逻辑一起绕过去了。"""
    import httpx as _httpx

    from app.core import http_retry as ai_retry

    transport = _httpx.MockTransport(handler)
    real = ai_retry.RetryingClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    # 只打 ai_retry 一处:LLM 节点现在经 domain/ai_chat 走 ai_retry.post,而 RetryingClient
    # 是在 ai_retry 自己的命名空间里 new 的。(module 参数保留只为不改各调用点的写法。)
    monkeypatch.setattr(ai_retry, "RetryingClient", patched)


def linear_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}, "config": {"params": {"topic": "海边"}}},
            {
                "id": "search",
                "type": "template",
                "name": "查资料",
                "position": {"x": 240, "y": 0},
                "config": {"template": "关于 {{start.topic}}"},
            },
        ],
        "edges": [{"id": "e1", "source": "start", "target": "search"}],
    }


def test_validate_graph_rules() -> None:
    assert validate_graph(default_graph()) == []
    assert validate_graph(linear_graph()) == []

    no_start = {"nodes": [{"id": "a", "type": "llm", "config": {"prompt": "x"}}], "edges": []}
    assert any("开始节点" in e for e in validate_graph(no_start))

    cycle = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "a", "type": "llm", "config": {"prompt": "x"}},
            {"id": "b", "type": "llm", "config": {"prompt": "y"}},
        ],
        "edges": [
            {"id": "e1", "source": "a", "target": "b"},
            {"id": "e2", "source": "b", "target": "a"},
        ],
    }
    assert any("环路" in e for e in validate_graph(cycle))

    missing_required = {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "l", "type": "llm", "config": {}}],
        "edges": [],
    }
    assert any("必填配置" in e for e in validate_graph(missing_required))

    bad_edge = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": [{"id": "e", "source": "start", "target": "ghost"}]}
    assert any("不存在的节点" in e for e in validate_graph(bad_edge))


def data_edge_graph() -> dict:
    """LLM.text 经数据边喂给 template 节点的必填 template 输入(字面量留空)。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "llm-1", "type": "llm", "config": {"prompt": "hi"}},
            {"id": "tmpl", "type": "template", "config": {"template": ""}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "llm-1"},
            {
                "id": "d1",
                "source": "llm-1",
                "target": "tmpl",
                "kind": "data",
                "source_output": "text",
                "target_input": "template",
            },
        ],
    }


def test_data_edge_satisfies_required_and_orders() -> None:
    # 必填 template 字面量为空,但被数据边绑定 → 校验通过。
    assert validate_graph(data_edge_graph()) == []
    # 数据边也是排序约束:llm-1 排在 tmpl 前。
    order = [node["id"] for node in topo_order(data_edge_graph())]
    assert order.index("llm-1") < order.index("tmpl")


def test_apply_data_edges_binds_input() -> None:
    from app.domain.workflows.binding import apply_data_edges

    edges = data_edge_graph()["edges"]
    context = {"llm-1": {"text": "你好世界"}}
    config = apply_data_edges("tmpl", {"template": ""}, edges, context)
    assert config["template"] == "你好世界"
    # 上游还没跑(不在 context)→ 不绑定,保留原字面量。
    config2 = apply_data_edges("tmpl", {"template": "orig"}, edges, {})
    assert config2["template"] == "orig"


def test_topo_and_interpolate() -> None:
    order = [node["id"] for node in topo_order(linear_graph())]
    assert order == ["start", "search"]

    ctx = {"start": {"topic": "海边", "count": 3}}
    assert interpolate("主题是{{start.topic}}", ctx) == "主题是海边"
    # 整串引用保留原类型
    assert interpolate("{{start.count}}", ctx) == 3
    assert interpolate({"q": "{{start.topic}}!"}, ctx) == {"q": "海边!"}


def test_workflow_crud_and_run() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    created = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "测试流", "description": "先查库", "graph": linear_graph()},
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["id"]

    listed = client.get(f"/api/workflows?workspace_id={ws['id']}").json()
    assert [w["name"] for w in listed] == ["测试流"]

    duplicated_start = linear_graph()
    duplicated_start["nodes"].append({"id": "start-2", "type": "start", "name": "开始 2", "config": {}})
    bad = client.patch(f"/api/workflows/{workflow_id}", json={"graph": duplicated_start})
    assert bad.status_code == 422

    types = client.get("/api/workflows/node-types").json()
    assert {t["type"] for t in types} >= {"start", "llm", "template", "plugin_tool"}

    run = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {"topic": "山顶"}})
    assert run.status_code == 200, run.text
    job_id = run.json()["id"]

    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert status == "succeeded"

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        # start 的默认参数被运行参数覆盖
        assert job.result["context"]["start"]["topic"] == "山顶"
        events = db.query(TaskEvent).filter(TaskEvent.job_id == job_id).all()
        types_seen = {event.type for event in events}
        assert "workflow.node.started" in types_seen
        assert "workflow.finished" in types_seen

    empty = client.patch(f"/api/workflows/{workflow_id}", json={"graph": {"nodes": [], "edges": []}})
    assert empty.status_code == 200, empty.text
    blocked_run = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
    assert blocked_run.status_code == 422
    assert "开始节点" in blocked_run.text

    gone = client.delete(f"/api/workflows/{workflow_id}")
    assert gone.status_code == 204


def test_workflow_revisions_are_immutable_and_restore_appends() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "版本工作区"}).json()
    original = linear_graph()
    created = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "可追溯工作流", "graph": original},
    )
    assert created.status_code == 200, created.text
    workflow = created.json()
    assert workflow["revision"] == 1
    assert len(workflow["graph_hash"]) == 64

    # 相同内容和纯元数据修改不制造空修订。
    same = client.patch(f"/api/workflows/{workflow['id']}", json={"name": "已改名", "graph": original})
    assert same.status_code == 200, same.text
    assert same.json()["revision"] == 1

    edited = linear_graph()
    edited["nodes"][1]["config"]["template"] = "围绕 {{start.topic}} 写一句"
    changed = client.patch(f"/api/workflows/{workflow['id']}", json={"graph": edited})
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 2

    revisions = client.get(f"/api/workflows/{workflow['id']}/revisions").json()
    assert [item["revision"] for item in revisions] == [2, 1]
    assert revisions[0]["graph_hash"] != revisions[1]["graph_hash"]
    first = client.get(f"/api/workflows/{workflow['id']}/revisions/1").json()
    assert first["graph"] == original

    restored = client.post(f"/api/workflows/{workflow['id']}/revisions/1/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["revision"] == 3
    assert restored.json()["graph"] == original
    latest = client.get(f"/api/workflows/{workflow['id']}/revisions").json()[0]
    assert latest["source"] == "restore"
    assert latest["note"] == "v1"

    exported = client.get(f"/api/workflows/{workflow['id']}/export").json()
    assert exported["workflow_revision"] == 3
    assert exported["graph_hash"] == restored.json()["graph_hash"]

    run = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}})
    assert run.status_code == 200, run.text
    with SessionLocal() as db:
        job = db.get(Job, run.json()["id"])
        assert job is not None
        assert job.payload["workflow_revision"] == 3
        assert job.payload["workflow_graph_hash"] == restored.json()["graph_hash"]
        assert job.payload["workflow_revision_id"]


def test_queued_run_executes_the_revision_pinned_at_enqueue(monkeypatch) -> None:
    """排队后继续编辑画布，已经创建的任务仍执行原图。"""

    from app.domain.workflows import engine as workflow_engine

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "Pinned"}).json()
    pending: dict[str, object] = {}

    class DeferredThread:
        def __init__(self, *, target, args, daemon):
            pending.update(target=target, args=args, daemon=daemon)

        def start(self) -> None:
            return None

    real_thread = workflow_engine.threading.Thread
    monkeypatch.setattr(workflow_engine.threading, "Thread", DeferredThread)
    before = linear_graph()
    before["nodes"][1]["config"]["template"] = "入队前"
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws["id"], name="固定修订", graph=before)
        job = workflow_engine.start_workflow_job(db, workflow, created_by=None)
        job_id = job.id
        monkeypatch.setattr(workflow_engine.threading, "Thread", real_thread)

        after = linear_graph()
        after["nodes"][1]["config"]["template"] = "入队后"
        update_workflow(db, workflow, {"graph": after})

    target = pending["target"]
    assert callable(target)
    target(*pending["args"])

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "succeeded"
        assert job.payload["workflow_revision"] == 1
        assert job.result["workflow_revision"] == 1
        assert job.result["context"]["search"]["text"] == "入队前"


def test_branching_code_and_template_nodes() -> None:
    """条件分支只走匹配侧;code/template 节点产出可被下游引用。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"topic": "海边旅行"}}},
            {
                "id": "check",
                "type": "condition",
                "config": {"left": "{{start.topic}}", "op": "contains", "right": "海边"},
            },
            {"id": "yes", "type": "template", "config": {"template": "命中:{{start.topic}}"}},
            {"id": "no", "type": "template", "config": {"template": "未命中"}},
            {
                "id": "count",
                "type": "code",
                "config": {"code": "output = len(inputs['text'])", "input": {"text": "{{yes.text}}"}},
            },
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "check"},
            {"id": "e2", "source": "check", "target": "yes", "source_handle": "true"},
            {"id": "e3", "source": "check", "target": "no", "source_handle": "false"},
            {"id": "e4", "source": "yes", "target": "count"},
        ],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "分支流", "graph": graph})
    assert workflow.status_code == 200, workflow.text

    run = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job

    context = job["result"]["context"]
    assert context["check"]["result"] is True
    assert context["yes"]["text"] == "命中:海边旅行"
    assert context["count"]["output"] == len("命中:海边旅行")
    assert "no" not in context  # 假分支整段跳过

    with SessionLocal() as db:
        events = db.query(TaskEvent).filter(TaskEvent.job_id == job_id).all()
        skipped = [e.payload["node_id"] for e in events if e.type == "workflow.node.skipped"]
        assert skipped == ["no"]


def test_loop_foreach_iterates_body_and_feeds_downstream() -> None:
    """foreach 循环:对列表逐项跑内嵌子图(用 {{loop.item}}/{{loop.index}}),
    结果汇总成列表并可被下游节点消费。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    body = {
        "nodes": [{"id": "fmt", "type": "template", "config": {"template": "第{{loop.index}}项:{{loop.item}}"}}],
        "edges": [],
    }
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"names": ["甲", "乙", "丙"]}}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": "{{start.names}}", "body": body, "output": "{{fmt.text}}"}},
            {"id": "join", "type": "code", "config": {"code": "output = ' | '.join(inputs['items'])", "input": {"items": "{{loop.results}}"}}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "loop"},
            {"id": "e2", "source": "loop", "target": "join"},
        ],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "循环流", "graph": graph})
    assert workflow.status_code == 200, workflow.text

    run = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job

    context = job["result"]["context"]
    assert context["loop"]["count"] == 3
    # The join node proves the actual per-iteration outputs were collected in order and consumable.
    assert context["join"]["output"] == "第0项:甲 | 第1项:乙 | 第2项:丙"


def test_loop_while_repeats_until_condition_false() -> None:
    """while 循环:每轮跑内嵌子图,子图里的条件节点决定是否继续;带最大次数上限。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    body = {
        "nodes": [{"id": "check", "type": "condition", "config": {"left": "{{loop.index}}", "op": "lt", "right": "2"}}],
        "edges": [],
    }
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "loop", "type": "loop_while", "config": {"body": body, "condition": "{{check.result}}", "max_iterations": 10}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "条件循环", "graph": graph})
    assert workflow.status_code == 200, workflow.text
    run = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job
    # index 0,1 → check true (continue); index 2 → 2<2 false → stop. 3 runs total.
    assert job["result"]["context"]["loop"]["iterations"] == 3


def test_loop_while_respects_max_iterations() -> None:
    """条件恒真时 max_iterations 兜底,不会无限循环。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    body = {"nodes": [{"id": "t", "type": "template", "config": {"template": "{{loop.index}}"}}], "edges": []}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "loop", "type": "loop_while", "config": {"body": body, "condition": "yes", "max_iterations": 4}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "兜底", "graph": graph})
    run = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job
    assert job["result"]["context"]["loop"]["iterations"] == 4


def test_loop_foreach_rejects_start_in_body() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    body = {"nodes": [{"id": "s", "type": "start", "config": {}}], "edges": []}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": "{{start.x}}", "body": body}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "loop"}],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "坏循环", "graph": graph})
    assert workflow.status_code == 200, workflow.text  # outer graph is valid; body checked at run time
    run = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {"x": ["a"]}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "failed", job


def test_asset_query_filters_and_feeds_loop() -> None:
    """asset_query 按条件批量选素材,输出列表可直接喂给 foreach 逐个处理。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    proj = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()

    def mk(kind: str, name: str, tags: list[str] | None = None) -> dict:
        asset = client.post(
            "/api/assets",
            json={"workspace_id": ws["id"], "project_id": proj["id"], "kind": kind, "name": name,
                  "file_key": f"media/{name}", "media_info": {"duration": 3}},
        ).json()
        if tags:
            client.patch(f"/api/assets/{asset['id']}", json={"tags": tags})
        return asset

    mk("video", "hero_a.mp4", ["hero"])
    mk("video", "b.mp4")
    mk("image", "c.png", ["hero"])

    # asset_query(kind=video) → 2 videos; loop formats each item's name.
    body = {"nodes": [{"id": "fmt", "type": "template", "config": {"template": "clip:{{loop.item.name}}"}}], "edges": []}
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "q", "type": "asset_query", "config": {"kind": "video"}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": "{{q.assets}}", "body": body, "output": "{{fmt.text}}"}},
            {"id": "join", "type": "code", "config": {"code": "output = ' | '.join(inputs['r'])", "input": {"r": "{{loop.results}}"}}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "q"},
            {"id": "e2", "source": "q", "target": "loop"},
            {"id": "e3", "source": "loop", "target": "join"},
        ],
    }
    wf = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "选素材", "graph": graph})
    assert wf.status_code == 200, wf.text
    run = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job
    ctx = job["result"]["context"]
    assert ctx["q"]["count"] == 2
    # Newest-first: b.mp4 then hero_a.mp4; loop ran over each video's name.
    assert set(ctx["join"]["output"].split(" | ")) == {"clip:b.mp4", "clip:hero_a.mp4"}


def test_json_extract_node() -> None:
    from app.domain.workflows.executors.basic import json_extract

    src = '{"data": {"items": [{"title": "hello"}, {"title": "world"}]}}'
    assert json_extract(None, None, {"source": src, "path": "data.items.0.title"}) == {
        "value": "hello", "text": "hello",
    }
    # missing path → None/""; already-parsed dict source works too
    assert json_extract(None, None, {"source": {"a": 1}, "path": "b"}) == {"value": None, "text": ""}
    # whole object when path empty → JSON text
    out = json_extract(None, None, {"source": {"a": 1}, "path": ""})
    assert out["value"] == {"a": 1} and out["text"] == '{"a": 1}'


def test_text_transform_node() -> None:
    from app.domain.workflows.executors.basic import text_transform

    assert text_transform(None, None, {"text": "  Hi ", "op": "trim"})["text"] == "Hi"
    assert text_transform(None, None, {"text": "abc", "op": "upper"})["text"] == "ABC"
    assert text_transform(None, None, {"text": "a-b-c", "op": "replace", "find": "-", "replace": "_"})["text"] == "a_b_c"
    assert text_transform(None, None, {"text": "id=42 x", "op": "regex_extract", "find": r"id=(\d+)"})["text"] == "42"
    assert text_transform(None, None, {"text": "hello", "op": "length"}) == {"text": "5", "length": 1}


def test_delay_node_clamps(monkeypatch) -> None:
    from app.domain.workflows.executors import basic

    slept: list[float] = []
    monkeypatch.setattr(basic.time, "sleep", lambda s: slept.append(s))  # never actually block
    assert basic.delay(None, None, {"seconds": 0})["waited"] == 0.0
    assert basic.delay(None, None, {"seconds": 99999})["waited"] == 300.0  # clamped to max
    assert basic.delay(None, None, {"seconds": "oops"})["waited"] == 1.0  # unparsable → default 1
    assert basic.delay(None, None, {})["waited"] == 1.0  # default
    assert slept == [0.0, 300.0, 1.0, 1.0]


def test_translate_node_google(monkeypatch) -> None:
    from app.domain.workflows.executors import ai as ai_nodes

    monkeypatch.setattr("app.domain.translate.google_translate", lambda text, target, source="auto": f"[{target}]{text}")
    assert ai_nodes.translate(None, None, {"text": "hi", "target_lang": "zh-CN"}) == {"text": "[zh-CN]hi"}
    assert ai_nodes.translate(None, None, {"text": "  ", "target_lang": "en"}) == {"text": ""}  # empty short-circuit


def test_llm_node_sends_advanced_openai_payload_and_parses_json(monkeypatch) -> None:
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    captured: dict = {}

    def handler(request):
        import json as _json

        captured.update(
            {
                "url": str(request.url),
                "headers": request.headers,
                "json": _json.loads(request.content),
                # 超时现在设在 Client 上,httpx 把它作为 extension 挂到每个 request 上带下来。
                "timeout": (request.extensions.get("timeout") or {}).get("read"),
            }
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"title":"海边"}'}}]})

    _install_llm_transport(monkeypatch, ai_nodes, handler)

    with SessionLocal() as db:
        profile = add_provider(
            db,
            name="LLM",
            vendor="openai-compatible",
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="gpt-default",
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()

        with acting_as(db):
            result = ai_nodes.llm(
                db,
                workflow,
                {
                    "profile_id": profile.id,
                    "system": "只返回 JSON",
                    "prompt": "生成标题",
                    "model": "gpt-custom",
                    "temperature": "0.2",
                    "top_p": "0.8",
                    "max_tokens": "128",
                    "frequency_penalty": "0.1",
                    "presence_penalty": "0.2",
                    "seed": "42",
                    "stop": "END\nDONE",
                    "response_format": "json_schema",
                    "json_schema_name": "scene_plan",
                    "json_schema_strict": "true",
                    "json_schema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    },
                },
            )

    assert result == {"text": '{"title":"海边"}', "json": {"title": "海边"}}
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["timeout"] == ai_nodes.LLM_TIMEOUT_SECONDS
    assert captured["json"] == {
        "model": "gpt-custom",
        "messages": [{"role": "system", "content": "只返回 JSON"}, {"role": "user", "content": "生成标题"}],
        "temperature": 0.2,
        "top_p": 0.8,
        "frequency_penalty": 0.1,
        "presence_penalty": 0.2,
        "max_tokens": 128,
        "seed": 42,
        "stop": ["END", "DONE"],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "scene_plan",
                "schema": {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
                "strict": True,
            },
        },
    }


def test_llm_node_falls_back_when_provider_rejects_response_format(monkeypatch) -> None:
    """官方工作流不能因为默认聊天模型不实现 response_format 就整条失败。"""
    import json as _json

    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    attempts: list[dict] = []

    def handler(request):
        payload = _json.loads(request.content)
        attempts.append(payload)
        if payload.get("response_format"):
            return httpx.Response(
                400,
                json={"error": {"message": "This response_format type is unavailable now"}},
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"title":"海边"}'}}]})

    _install_llm_transport(monkeypatch, ai_nodes, handler)

    with SessionLocal() as db:
        profile = add_provider(
            db,
            name="LLM",
            vendor="openai-compatible",
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="deepseek-v4-flash",
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()

        with acting_as(db):
            result = ai_nodes.llm(
                db,
                workflow,
                {
                    "profile_id": profile.id,
                    "prompt": "生成标题",
                    "response_format": "json_schema",
                    "json_schema_name": "title",
                    "json_schema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                        "additionalProperties": False,
                    },
                },
            )

    assert result == {"text": '{"title":"海边"}', "json": {"title": "海边"}}
    assert [one.get("response_format", {}).get("type") for one in attempts] == [
        "json_schema",
        "json_object",
        None,
    ]
    fallback_messages = attempts[-1]["messages"]
    assert any(
        "JSON Schema" in str(one.get("content")) and '"title"' in str(one.get("content"))
        for one in fallback_messages
    )


def test_llm_node_locally_validates_schema_after_provider_response(monkeypatch) -> None:
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install_llm_transport(
        monkeypatch,
        ai_nodes,
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": '{"title":7}'}}]}),
    )

    with SessionLocal() as db:
        profile = add_provider(
            db, name="LLM", vendor="openai-compatible", base_url="https://example.test/v1", api_key="sk", model="m"
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        with acting_as(db), pytest.raises(WorkflowDomainError, match="不符合 Schema"):
            ai_nodes.llm(
                db,
                workflow,
                {
                    "profile_id": profile.id,
                    "prompt": "生成标题",
                    "response_format": "json_schema",
                    "json_schema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    },
                },
            )


def test_llm_node_uses_the_tool_free_gateway_for_oauth(monkeypatch) -> None:
    from app.ai.sidecar import adapters
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    captured: dict = {}

    def fake_gateway(**kwargs):
        captured.update(kwargs)
        return adapters.GatewayResult(text="订阅模型回答", usage={"input": 7, "output": 3})

    monkeypatch.setattr(adapters, "gateway_complete", fake_gateway)
    with SessionLocal() as db:
        profile = add_provider(
            db,
            name="Kimi Code",
            vendor="kimi-coding",
            base_url="",
            auth_type="oauth",
            oauth_credential={"access_token": "x"},
            model="k3",
            capability_ids=["chat"],
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        with acting_as(db):
            result = ai_nodes.llm(db, workflow, {"profile_id": profile.id, "prompt": "写一句"})

    assert result == {"text": "订阅模型回答"}
    assert captured["provider"]["pi_provider"] == "kimi-coding"
    assert captured["model"] == "k3"
    assert captured["prompt"] == "写一句"


def test_llm_node_rejects_invalid_json_response(monkeypatch) -> None:
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    _install_llm_transport(
        monkeypatch,
        ai_nodes,
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
    )

    with SessionLocal() as db:
        profile = add_provider(
            db, name="LLM", vendor="openai-compatible", base_url="https://example.test/v1", api_key="sk", model="m"
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()

        try:
            with acting_as(db):
                ai_nodes.llm(db, workflow, {"profile_id": profile.id, "prompt": "x", "response_format": "json_object"})
        except WorkflowDomainError as exc:
            assert "合法 JSON" in str(exc)
        else:
            raise AssertionError("expected WorkflowDomainError")


def test_llm_node_surfaces_provider_error_body(monkeypatch) -> None:
    # 400 等 4xx 时,把供应商响应体里的原因带出来(否则日志只剩裸状态码,查不出根因)。
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    _install_llm_transport(
        monkeypatch,
        ai_nodes,
        lambda request: httpx.Response(
            400, json={"error": {"message": "response_format.type must be one of text, json_object"}}
        ),
    )

    with SessionLocal() as db:
        profile = add_provider(
            db,
            name="LLM",
            vendor="openai-compatible",
            base_url="https://api.deepseek.com",
            api_key="sk",
            model="deepseek-chat",
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()

        try:
            with acting_as(db):
                ai_nodes.llm(db, workflow, {"profile_id": profile.id, "prompt": "hi"})
        except WorkflowDomainError as exc:
            msg = str(exc)
            assert "400" in msg
            assert "deepseek-chat" in msg
            assert "response_format.type must be one of" in msg
        else:
            raise AssertionError("expected WorkflowDomainError")


def test_llm_node_rejects_empty_prompt(monkeypatch) -> None:
    # 空提示词提前拦下(不打网络),给出可操作的中文提示。
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    def handler(request):
        raise AssertionError("空提示词不应发起网络请求")

    _install_llm_transport(monkeypatch, ai_nodes, handler)

    with SessionLocal() as db:
        profile = add_provider(
            db, name="LLM", vendor="openai-compatible", base_url="https://example.test/v1", api_key="sk"
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()

        try:
            with acting_as(db):
                ai_nodes.llm(db, workflow, {"profile_id": profile.id, "prompt": "   "})
        except WorkflowDomainError as exc:
            assert "提示词为空" in str(exc)
        else:
            raise AssertionError("expected WorkflowDomainError")


def test_new_nodes_registered_and_validate() -> None:
    from app.domain.workflows.executors import registered_types

    for node_type in ("json_extract", "text_transform", "delay", "synthesize_speech", "notify"):
        assert node_type in NODE_TYPES, node_type
        assert node_type in registered_types(), node_type
    assert "json" in NODE_TYPES["llm"]["outputs"]
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "d", "type": "delay", "config": {"seconds": 1}},
            {"id": "n", "type": "notify", "config": {"title": "done"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "d"},
            {"id": "e2", "source": "d", "target": "n"},
        ],
    }
    assert validate_graph(graph) == []


def test_condition_operators_and_bad_branch_handle() -> None:
    from app.domain.workflows import validate_graph
    from app.domain.workflows.executors.basic import condition

    assert condition(None, None, {"left": "5", "op": "gt", "right": "3"})["result"] is True
    assert condition(None, None, {"left": "", "op": "empty"})["result"] is True
    assert condition(None, None, {"left": "abc", "op": "not_contains", "right": "x"})["result"] is True

    bad = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "c", "type": "condition", "config": {"left": "a", "op": "equals", "right": "a"}},
            {"id": "t", "type": "template", "config": {"template": "x"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "c"},
            {"id": "e2", "source": "c", "target": "t", "source_handle": "maybe"},
        ],
    }
    assert any("true/false" in error for error in validate_graph(bad))


def test_workflow_tools_via_confirmations() -> None:
    """智能体路径:create/update/run_workflow 走确认卡,批准后才执行。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    created = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "create_workflow",
            "requested_by": "mcp-agent",
            "payload": {"name": "智能体流", "description": "", "graph": linear_graph()},
        },
    )
    assert created.status_code == 200, created.text
    confirmation_id = created.json()["id"]
    assert created.json()["status"] == "pending"

    # 未批准前工作流不存在
    assert client.get(f"/api/workflows?workspace_id={ws['id']}").json() == []

    approved = client.post(f"/api/confirmations/{confirmation_id}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    workflow_id = approved.json()["result"]["workflow_id"]

    listed = client.get(f"/api/workflows?workspace_id={ws['id']}").json()
    assert [w["name"] for w in listed] == ["智能体流"]

    # 非法图在请求确认时就被拒(不产生确认卡):多个 start 仍不允许。
    duplicated_start = linear_graph()
    duplicated_start["nodes"].append({"id": "start-2", "type": "start", "name": "开始 2", "config": {}})
    bad = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "update_workflow",
            "payload": {"workflow_id": workflow_id, "graph": duplicated_start},
        },
    )
    assert bad.status_code == 422

    ran = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "run_workflow", "payload": {"workflow_id": workflow_id, "params": {}}},
    )
    run_approved = client.post(f"/api/confirmations/{ran.json()['id']}/approve")
    assert run_approved.json()["status"] == "executed"
    job_id = run_approved.json()["result"]["job_id"]

    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert status == "succeeded"


def test_scheduled_task_dispatches_workflow() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "定时流", "graph": default_graph()},
    ).json()

    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "跑定时流",
            "kind": "workflow",
            "trigger_type": "manual",
            "schedule": {},
            "payload": {"workflow_id": workflow["id"], "params": {}},
        },
    )
    assert task.status_code == 200, task.text

    fired = client.post(f"/api/scheduled-tasks/{task.json()['id']}/run")
    assert fired.status_code == 200, fired.text
    job_id = fired.json()["job"]["id"]

    from app.workers.scheduler import dispatch_job_for_task  # noqa: F401 — run 路由已内联派发

    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert status == "succeeded", status


def test_cancel_running_workflow() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "慢流", "graph": {
            "nodes": [
                {"id": "start", "type": "start", "config": {"params": {}}},
                {"id": "slow", "type": "code", "config": {"code": "import time\ntime.sleep(2)\noutput = {'ok': 1}"}},
                {"id": "after", "type": "template", "config": {"template": "{{slow.ok}}"}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "slow"},
                {"id": "e2", "source": "slow", "target": "after"},
            ],
        }},
    ).json()
    job_id = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}}).json()["id"]

    time.sleep(0.3)  # 让引擎进入 slow 节点
    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["error"] == "已取消"

    # 引擎在节点边界停下:job 保持取消态,不会被后续节点改写成 succeeded
    for _ in range(60):
        job = client.get(f"/api/jobs/{job_id}").json()
        time.sleep(0.1)
    assert job["status"] == "failed"
    assert job["error"] == "已取消"

    # 已结束的任务再取消 → 409
    again = client.post(f"/api/jobs/{job_id}/cancel")
    assert again.status_code == 409

    # 在飞的节点必须有终态事件:只有 started 没有收尾的话,前端(按 started/finished 配对)
    # 会把它永远显示成运行中,耗时按「现在 − 开始」一直往上走。
    events = client.get(f"/api/jobs/{job_id}/events").json()
    by_node: dict[str, set[str]] = {}
    for e in events:
        nid = (e.get("payload") or {}).get("node_id")
        if nid:
            by_node.setdefault(nid, set()).add(e["type"])
    assert "slow" in by_node, f"没有 slow 节点的事件: {[e['type'] for e in events]}"
    assert by_node["slow"] & {"workflow.node.finished", "workflow.node.failed"}, (
        f"取消时在飞的节点没有终态事件: {by_node['slow']}"
    )
    # 事件按时间**正序**返回,且早期事件不被截断(旧实现取最新 30 条,会把开头的 started 挤掉)
    assert [e["created_at"] for e in events] == sorted(e["created_at"] for e in events)
    assert any(e["type"] == "workflow.node.started" and (e.get("payload") or {}).get("node_id") == "start"
               for e in events), "最早的节点事件被截断了"

def test_parallel_fanout_and_join() -> None:
    """纯分流并发:start 拉两条控制边到 a/b(都跑),再各拉一条到 join(join 只跑一次、在两者之后)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"t": "X"}}},
            {"id": "a", "type": "template", "config": {"template": "A:{{start.t}}"}},
            {"id": "b", "type": "template", "config": {"template": "B:{{start.t}}"}},
            {"id": "join", "type": "template", "config": {"template": "{{a.text}}|{{b.text}}"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "a"},
            {"id": "e2", "source": "start", "target": "b"},
            {"id": "e3", "source": "a", "target": "join"},
            {"id": "e4", "source": "b", "target": "join"},
        ],
    }
    wf = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "并行", "graph": graph})
    assert wf.status_code == 200, wf.text
    run = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job
    ctx = job["result"]["context"]
    assert ctx["a"]["text"] == "A:X"
    assert ctx["b"]["text"] == "B:X"  # 两条分流都跑了
    assert ctx["join"]["text"] == "A:X|B:X"  # join 拿到两侧、只跑一次

def test_parallel_branches_run_concurrently() -> None:
    """两条独立分支必须真并发:各自记录执行区间,断言两段**重叠**。

    这里刻意不用「总墙钟 < 阈值」来间接推断并发。那种写法要在 2s(串行)之下留阈值,而余量
    要同时容纳两次 Python 子进程冷启动、两轮 HTTP、任务派发和 0.1s 的轮询粒度——全量测试满载时
    必然溢出,于是这个测试会在与它无关的改动下随机变红。重叠是并发的**定义本身**,不受机器
    快慢影响:串行时 c2 的开始必然晚于 c1 的结束,重叠为零。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    # 输出 "开始,结束"。用字符串而不是 list:job.result 的上下文会经 _trim_outputs 收敛,
    # list 会被折成 "[2 items]",时间戳就没了。
    sleeper = "import time\n_s = time.time()\ntime.sleep(1.0)\noutput = f'{_s},{time.time()}'"
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "c1", "type": "code", "config": {"code": sleeper, "input": {}}},
            {"id": "c2", "type": "code", "config": {"code": sleeper, "input": {}}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "c1"},
            {"id": "e2", "source": "start", "target": "c2"},
        ],
    }
    wf = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "并发", "graph": graph})
    assert wf.status_code == 200, wf.text
    run = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "succeeded", job
    spans = {}
    for node in ("c1", "c2"):
        start, end = (float(x) for x in job["result"]["context"][node]["output"].split(","))
        assert end - start >= 0.9, f"{node} 没真的睡满 1s({end - start:.2f}s)"
        spans[node] = (start, end)
    overlap = min(spans["c1"][1], spans["c2"][1]) - max(spans["c1"][0], spans["c2"][0])
    assert overlap > 0.5, (
        f"两条 1s 分支只重叠了 {overlap:.2f}s,疑似未并发;"
        f"c1={spans['c1']} c2={spans['c2']}"
    )


def test_node_types_and_executor_registry_stay_in_lockstep() -> None:
    """NODE_TYPES 是节点的元数据接缝,executors 注册表是行为接缝——两边必须一一对应。

    少一边都意味着漂移:有元数据没执行器 = 画布能拖出一个跑不了的节点;有执行器没
    元数据 = 校验/画布/智能体都不知道它存在。"""
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.executors import registered_types

    assert set(NODE_TYPES) == set(registered_types())


def test_workflow_supports_multiple_agent_sessions() -> None:
    """一个工作流不止一个 AI 会话:默认会话 get-or-create,新会话带唯一后缀,
    列表把两类都按前缀归组返回。"""
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "WF"}).json()

    default = client.post(f"/api/workflows/{wf['id']}/agent-session").json()
    assert client.post(f"/api/workflows/{wf['id']}/agent-session").json()["id"] == default["id"]  # 幂等

    second = client.post(f"/api/workflows/{wf['id']}/agent-sessions").json()
    third = client.post(f"/api/workflows/{wf['id']}/agent-sessions").json()
    assert len({default["id"], second["id"], third["id"]}) == 3

    listed = client.get(f"/api/workflows/{wf['id']}/agent-sessions").json()
    assert {item["id"] for item in listed} == {default["id"], second["id"], third["id"]}

    # 别的工作流看不到这些会话
    other = client.post("/api/workflows", json={"workspace_id": ws, "name": "WF2"}).json()
    assert client.get(f"/api/workflows/{other['id']}/agent-sessions").json() == []


def test_workflow_export_import_roundtrip() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    created = client.post(
        "/api/workflows", json={"workspace_id": ws["id"], "name": "出海流程", "description": "desc", "graph": linear_graph()}
    ).json()

    # 导出:信封 + attachment 头(中文名走 RFC 5987)
    res = client.get(f"/api/workflows/{created['id']}/export")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    envelope = res.json()
    assert envelope["format"] == "mosael-workflow" and envelope["version"] == 1
    assert envelope["name"] == "出海流程"
    assert envelope["graph"] == linear_graph()

    # 导入:同名自动加序号,graph 原样落库
    imported = client.post("/api/workflows/import", json={"workspace_id": ws["id"], "data": envelope})
    assert imported.status_code == 200
    body = imported.json()
    assert body["name"] == "出海流程 (2)"
    assert body["graph"] == linear_graph()

    # 再导一次 → (3)
    assert client.post("/api/workflows/import", json={"workspace_id": ws["id"], "data": envelope}).json()["name"] == "出海流程 (3)"


def test_workflow_export_writes_the_current_format() -> None:
    """导出始终使用当前格式标识。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    created = client.post(
        "/api/workflows", json={"workspace_id": ws["id"], "name": "x", "graph": linear_graph()}
    ).json()
    res = client.get(f"/api/workflows/{created['id']}/export")
    assert res.json()["format"] == "mosael-workflow"
    assert "mosael-workflow.json" in res.headers["content-disposition"]


def test_workflow_import_rejects_bad_files() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    # 非本格式 / 缺 graph
    assert client.post("/api/workflows/import", json={"workspace_id": ws["id"], "data": {"format": "other"}}).status_code == 422
    assert (
        client.post(
            "/api/workflows/import", json={"workspace_id": ws["id"], "data": {"format": "mosael-workflow", "version": 1}}
        ).status_code
        == 422
    )

    # 版本过新
    too_new = {"format": "mosael-workflow", "version": 99, "name": "x", "graph": {"nodes": [], "edges": []}}
    res = client.post("/api/workflows/import", json={"workspace_id": ws["id"], "data": too_new})
    assert res.status_code == 422 and "版本" in res.json()["detail"]

    # 未知节点类型(伪造的新版文件)→ 明确报错而不是落一个坏图
    unknown_node = {
        "format": "mosael-workflow",
        "version": 1,
        "name": "x",
        "graph": {"nodes": [{"id": "n1", "type": "not-a-node", "config": {}}], "edges": []},
    }
    res = client.post("/api/workflows/import", json={"workspace_id": ws["id"], "data": unknown_node})
    assert res.status_code == 422 and "未知节点类型" in res.json()["detail"]


def test_每个节点类型都有分组和一句人话描述() -> None:
    """节点面板按分组呈现,分组顺序由 NODE_CATEGORIES 决定。

    漏标 category 不会报错,只会让那个节点静默掉进面板末尾的"其它"里 —— 加节点的人看不到,
    用节点的人找不到。描述同理:面板上每行都有一句说明,空着的那行就是一个只有作者看得懂
    的名字。"""
    from app.domain.workflows import NODE_CATEGORIES, NODE_TYPES

    for node_type, meta in NODE_TYPES.items():
        assert meta.get("category") in NODE_CATEGORIES, f"{node_type} 的分组不在 NODE_CATEGORIES 里"
        assert len(meta.get("description", "").strip()) >= 8, f"{node_type} 缺一句能读的描述"


def test_节点清单按分组顺序返回_前端不再排第二次() -> None:
    from tests.util import fresh_client

    from app.core.i18n import DEFAULT_LOCALE, t
    from app.domain.workflows import NODE_CATEGORIES

    client = fresh_client()
    items = client.get("/api/workflows/node-types").json()
    seen: list[str] = []
    for item in items:
        if item["category"] not in seen:
            seen.append(item["category"])
    #: 响应里的分组名是**翻过的**(它要显示在面板栏头上),而顺序按 key 排 —— 拿翻过的名字
    #: 去比,才是在比用户真正看到的那一排。
    expected = [t(c, DEFAULT_LOCALE) for c in NODE_CATEGORIES]
    assert seen == [c for c in expected if c in seen]


def test_llm_节点会把用量记进账(monkeypatch) -> None:
    """首页那张 Token 图和成本统计读的是 provider_usage_events。

    对话类调用以前一条都不记 —— 图上少的那部分不会有任何提示,看上去只是"这个月用得少"。
    统一走 domain/ai_chat 之后,给得出工作区的调用点都会记一条。
    """
    from app.db.models import ProviderUsageEvent
    from app.domain.workflows.executors import ai as ai_nodes

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    _install_llm_transport(
        monkeypatch,
        ai_nodes,
        lambda request: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            },
        ),
    )

    with SessionLocal() as db:
        profile = add_provider(
            db, name="LLM", vendor="openai-compatible", base_url="https://api.test", api_key="sk", model="m"
        )
        workflow = Workflow(workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        with acting_as(db):
            assert ai_nodes.llm(db, workflow, {"profile_id": profile.id, "prompt": "hi"})["text"] == "hi"
        db.commit()

    with SessionLocal() as db:
        events = db.query(ProviderUsageEvent).filter_by(workspace_id=workspace_id).all()
        assert len(events) == 1, "工作流 LLM 节点没有记用量"
        event = events[0]
        assert event.capability == "chat"
        assert event.operation == "workflow_llm"
        assert event.units["input_tokens"] == 11
        assert event.units["output_tokens"] == 7
