from __future__ import annotations

import time

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent, Workflow
from app.domain.workflows import default_graph, interpolate, topo_order, validate_graph
from tests.util import fresh_client


def linear_graph() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "position": {"x": 0, "y": 0}, "config": {"params": {"topic": "海边"}}},
            {
                "id": "search",
                "type": "kb_search",
                "name": "查资料",
                "position": {"x": 240, "y": 0},
                "config": {"query": "{{start.topic}}", "limit": 3},
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

    bad = client.patch(f"/api/workflows/{workflow_id}", json={"graph": {"nodes": [], "edges": []}})
    assert bad.status_code == 422

    types = client.get("/api/workflows/node-types").json()
    assert {t["type"] for t in types} >= {"start", "llm", "kb_search", "plugin_tool"}

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

    gone = client.delete(f"/api/workflows/{workflow_id}")
    assert gone.status_code == 204


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


def test_new_nodes_registered_and_validate() -> None:
    from app.domain.workflows import NODE_TYPES, validate_graph
    from app.domain.workflows.executors import registered_types

    for node_type in ("json_extract", "text_transform", "delay", "synthesize_speech", "notify"):
        assert node_type in NODE_TYPES, node_type
        assert node_type in registered_types(), node_type
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

    # 非法图在请求确认时就被拒(不产生确认卡)
    bad = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "update_workflow",
            "payload": {"workflow_id": workflow_id, "graph": {"nodes": [], "edges": []}},
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
    """两条独立分支各睡 1s:真并发则总墙钟 ≈ 1s(远小于串行的 2s)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    sleeper = "import time\ntime.sleep(1.0)\noutput = 1"
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
    started = time.monotonic()
    run = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"params": {}})
    job_id = run.json()["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    elapsed = time.monotonic() - started
    assert job["status"] == "succeeded", job
    assert job["result"]["context"]["c1"]["output"] == 1
    assert job["result"]["context"]["c2"]["output"] == 1
    # 串行会 ≥ 2s;并发应明显更短。给足子进程/调度开销余量。
    assert elapsed < 1.8, f"两条 1s 分支耗时 {elapsed:.2f}s,疑似未并发"


def test_node_types_and_executor_registry_stay_in_lockstep() -> None:
    """NODE_TYPES 是节点的元数据接缝,executors 注册表是行为接缝——两边必须一一对应。

    少一边都意味着漂移:有元数据没执行器 = 画布能拖出一个跑不了的节点;有执行器没
    元数据 = 校验/画布/智能体都不知道它存在。"""
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.executors import registered_types

    assert set(NODE_TYPES) == set(registered_types())
