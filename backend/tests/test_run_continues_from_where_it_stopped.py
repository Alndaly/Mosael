"""运行从中断处接着跑、从循环的第几轮重做:落定的节点不再执行,循环跑到一半不从头来(ADR 0092)。

30 段的续写跑到第 20 段断了,此前只能全部重跑,前面花的钱白花。这里用一个数调用次数的节点类型当「花钱的节点」:
每多跑一次都是多买一次。
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job, WorkflowRunStep
from app.domain.jobs import wait_for_idle_jobs
from app.domain.workflows import run_steps
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors import registry
from app.domain.workflows.executors import subjobs
from app.domain.workflows.run_scope import continuing_run, node_scope
from tests.util import fresh_client

CALLS: Counter[str] = Counter()
BROKEN: set[str] = set()


@pytest.fixture(autouse=True)
def _counting_node(monkeypatch):
    """模板节点换成会数次数、能指定在哪一项上失败的版本。"""
    CALLS.clear()
    BROKEN.clear()

    def spend(db: Any, scope: Any, config: dict[str, Any]) -> dict[str, Any]:
        text = str(config.get("template") or "")
        CALLS[text] += 1
        if text in BROKEN:
            raise WorkflowDomainError("wfErr_loopItems")
        return {"text": text}

    monkeypatch.setitem(registry._REGISTRY, "template", spend)


def _workflow(client, graph: dict) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    created = client.post("/api/workflows", json={"workspace_id": ws, "name": "接力", "graph": graph})
    assert created.status_code == 200, created.text
    return created.json()["id"], ws


def _run(client, wf_id: str) -> dict:
    started = client.post(f"/api/workflows/{wf_id}/run", json={"params": {}})
    assert started.status_code == 200, started.text
    wait_for_idle_jobs()
    return client.get(f"/api/jobs/{started.json()['id']}").json()


def _continue(client, wf_id: str, job_id: str) -> dict:
    resumed = client.post(f"/api/workflows/{wf_id}/runs/{job_id}/continue", json={})
    assert resumed.status_code == 200, resumed.text
    wait_for_idle_jobs()
    return client.get(f"/api/jobs/{job_id}").json()


LINE = {"nodes": [
    {"id": "start", "type": "start", "config": {}},
    {"id": "a", "type": "template", "config": {"template": "甲"}},
    {"id": "b", "type": "template", "config": {"template": "乙"}},
    {"id": "c", "type": "template", "config": {"template": "{{a.text}}{{b.text}}"}},
], "edges": [
    {"id": "e1", "source": "start", "target": "a"}, {"id": "e2", "source": "a", "target": "b"},
    {"id": "e3", "source": "b", "target": "c"},
]}


def test_顶层_落定的节点不再执行_失败的那个重跑() -> None:
    client = fresh_client()
    wf_id, _ = _workflow(client, LINE)
    BROKEN.add("乙")
    failed = _run(client, wf_id)
    assert failed["status"] == "failed" and CALLS["甲"] == 1

    BROKEN.clear()
    done = _continue(client, wf_id, failed["id"])
    assert done["status"] == "succeeded"
    assert CALLS["甲"] == 1, "落定的节点又跑了一遍 —— 又买了一次"
    assert CALLS["乙"] == 2 and CALLS["甲乙"] == 1
    assert done["error"] in (None, "")


def _chain(items: str) -> dict:
    body = {"nodes": [{"id": "seg", "type": "template", "config": {"template": "{{loop.item}}"}}], "edges": []}
    return {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "L", "type": "loop_foreach", "config": {"items": items, "body": body, "output": "{{seg.text}}"}},
        {"id": "tail", "type": "template", "config": {"template": "收尾"}},
    ], "edges": [{"id": "e1", "source": "start", "target": "L"}, {"id": "e2", "source": "L", "target": "tail"}]}


def test_循环断在第三轮_前两轮一步都不重做() -> None:
    client = fresh_client()
    wf_id, _ = _workflow(client, _chain("一\n二\n三\n四"))
    BROKEN.add("三")
    failed = _run(client, wf_id)
    assert failed["status"] == "failed" and CALLS["四"] == 0

    BROKEN.clear()
    done = _continue(client, wf_id, failed["id"])
    assert done["status"] == "succeeded"
    assert (CALLS["一"], CALLS["二"], CALLS["三"], CALLS["四"]) == (1, 1, 2, 1)
    assert done["result"]["context"]["L"]["results"] == ["一", "二", "三", "四"], "接着跑的循环交出的结果少了前面几轮"


def test_接力循环_继续之后上一轮的产物还接得上() -> None:
    client = fresh_client()
    body = {"nodes": [{"id": "seg", "type": "template", "config": {"template": "{{loop.previous}}{{loop.item}}"}}], "edges": []}
    wf_id, _ = _workflow(client, {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "L", "type": "loop_foreach", "config": {"items": "一\n二\n三", "body": body, "output": "{{seg.text}}"}},
    ], "edges": [{"id": "e1", "source": "start", "target": "L"}]})
    BROKEN.add("一二")
    failed = _run(client, wf_id)
    BROKEN.clear()
    done = _continue(client, wf_id, failed["id"])
    assert done["result"]["context"]["L"]["results"] == ["一", "一二", "一二三"]


def test_继续时改开始参数_只影响还没落定的节点() -> None:
    client = fresh_client()
    wf_id, _ = _workflow(client, {"nodes": [
        {"id": "start", "type": "start", "config": {"params": {"tail": "短"}}},
        {"id": "a", "type": "template", "config": {"template": "甲{{start.tail}}"}},
        {"id": "b", "type": "template", "config": {"template": "乙{{start.tail}}"}},
    ], "edges": [{"id": "e1", "source": "start", "target": "a"}, {"id": "e2", "source": "a", "target": "b"}]})
    BROKEN.add("乙短")
    failed = _run(client, wf_id)
    resumed = client.post(f"/api/workflows/{wf_id}/runs/{failed['id']}/continue", json={"params": {"tail": "长"}})
    assert resumed.status_code == 200, resumed.text
    wait_for_idle_jobs()
    done = client.get(f"/api/jobs/{failed['id']}").json()
    assert done["status"] == "succeeded"
    assert CALLS["甲短"] == 1 and CALLS["甲长"] == 0, "落定的节点不该因为改了参数重跑"
    assert CALLS["乙长"] == 1


def test_重做第二轮_换掉内容_前面留着_后面和下游重跑() -> None:
    client = fresh_client()
    wf_id, _ = _workflow(client, _chain("一\n二\n三"))
    job = _run(client, wf_id)
    assert job["status"] == "succeeded"
    redo = client.post(f"/api/workflows/{wf_id}/runs/{job['id']}/continue",
                       json={"redo": {"node_id": "L", "index": 1, "item": "新二"}})
    assert redo.status_code == 200, redo.text
    wait_for_idle_jobs()
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "succeeded"
    assert done["result"]["context"]["L"]["results"] == ["一", "新二", "三"]
    assert (CALLS["一"], CALLS["二"], CALLS["新二"], CALLS["三"]) == (1, 1, 1, 2)
    assert CALLS["收尾"] == 2, "循环下游的节点要跟着重跑"


def test_重做的节点不是循环_拒() -> None:
    client = fresh_client()
    wf_id, _ = _workflow(client, LINE)
    job = _run(client, wf_id)
    assert client.post(f"/api/workflows/{wf_id}/runs/{job['id']}/continue",
                       json={"redo": {"node_id": "a", "index": 0}}).status_code == 422


def test_子工作流断了_外层继续时它也接着跑_跑完的节点不重跑() -> None:
    client = fresh_client()
    inner_id, ws = _workflow(client, {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "x", "type": "template", "config": {"template": "内甲"}},
        {"id": "y", "type": "template", "config": {"template": "内乙"}},
        {"id": "out", "type": "output", "config": {"outputs": {"text": "{{y.text}}"}}},
    ], "edges": [{"id": "e1", "source": "start", "target": "x"}, {"id": "e2", "source": "x", "target": "y"},
                 {"id": "e3", "source": "y", "target": "out"}]})
    outer = client.post("/api/workflows", json={"workspace_id": ws, "name": "外层", "graph": {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "call", "type": "call_workflow", "config": {"workflow_id": inner_id}},
    ], "edges": [{"id": "e1", "source": "start", "target": "call"}]}})
    assert outer.status_code == 200, outer.text
    BROKEN.add("内乙")
    failed = _run(client, outer.json()["id"])
    assert failed["status"] == "failed" and CALLS["内甲"] == 1
    BROKEN.clear()
    done = _continue(client, outer.json()["id"], failed["id"])
    assert done["status"] == "succeeded", done["error"]
    assert CALLS["内甲"] == 1 and CALLS["内乙"] == 2


def test_成功的运行和点两下_都不让继续() -> None:
    client = fresh_client()
    wf_id, _ = _workflow(client, LINE)
    job = _run(client, wf_id)
    assert client.post(f"/api/workflows/{wf_id}/runs/{job['id']}/continue", json={}).status_code == 422


ASKED = {"prompt": "雨夜"}


def _held_step(ws: str, status: str) -> tuple[str, str]:
    with SessionLocal() as db:
        parent = Job(workspace_id=ws, kind="workflow", status="failed")
        child = Job(workspace_id=ws, kind="ai_generation", status=status)
        db.add_all([parent, child])
        db.flush()
        generation = GenerationJob(workspace_id=ws, job_id=child.id, provider="p", model="m", kind="video")
        db.add(generation)
        db.flush()
        db.add(WorkflowRunStep(job_id=parent.id, scope="", node_id="gen", held={run_steps._order_key(ASKED): child.id}))
        db.commit()
        return parent.id, generation.id


@pytest.mark.parametrize("status,reattached", [("running", True), ("succeeded", True), ("failed", False), ("cancelled", False)])
def test_交出去的生成单_还在就接回来_失败了才重新下(monkeypatch, status: str, reattached: bool) -> None:
    from app.domain.jobs import reset_parent_job, set_parent_job

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, generation_id = _held_step(ws, status)
    token = set_parent_job(parent_id)
    try:
        with SessionLocal() as db, continuing_run(True), node_scope("gen"):
            held = run_steps.held_generation(db, ASKED)
    finally:
        reset_parent_job(token)
    assert (held is not None) is reattached
    if reattached:
        assert held[0] == generation_id


def test_不是继续时_不接回任何单() -> None:
    from app.domain.jobs import reset_parent_job, set_parent_job

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, _ = _held_step(ws, "running")
    token = set_parent_job(parent_id)
    try:
        with SessionLocal() as db, node_scope("gen"):
            assert run_steps.held_generation(db, ASKED) is None
    finally:
        reset_parent_job(token)


def test_生成节点接回单时不再下单(monkeypatch) -> None:
    client = fresh_client()
    fresh = {"created": 0}

    def create(*_a: Any, **_k: Any) -> Any:
        fresh["created"] += 1
        raise AssertionError("又下了一次单")

    monkeypatch.setattr(subjobs.generation_operations, "create_generation_job", create)
    monkeypatch.setattr(subjobs.run_steps, "held_generation", lambda db, what: ("g", "c"))
    waited: list[str] = []
    monkeypatch.setattr(subjobs, "wait_for_job", lambda job_id, release: waited.append(job_id))
    db = SimpleNamespace(get=lambda model, _id: SimpleNamespace(
        id="g", result_asset_id="接回来的", result={"asset_ids": ["接回来的"]}))
    assert subjobs.ai_generate(db, None, {"kind": "video"})["asset_id"] == "接回来的"
    assert fresh["created"] == 0 and waited == ["c"] and client is not None


def _in_node(ws: str, status: str = "running") -> tuple[str, str]:
    """一条断了的运行,节点 gen 为 ASKED 下过一张单。交回 (运行 id, 单的 id)。"""
    with SessionLocal() as db:
        parent = Job(workspace_id=ws, kind="workflow", status="failed")
        child = Job(workspace_id=ws, kind="voice_synthesis", status=status)
        db.add_all([parent, child])
        db.flush()
        db.add(WorkflowRunStep(job_id=parent.id, scope="", node_id="gen", held={run_steps._order_key(ASKED): child.id}))
        db.commit()
        return parent.id, child.id


def _order_again(parent_id: str, what: Any, place: Any) -> str:
    from app.domain.jobs import reset_parent_job, set_parent_job

    token = set_parent_job(parent_id)
    try:
        with SessionLocal() as db, continuing_run(True), node_scope("gen"):
            job_id = run_steps.ordered(db, what, place)
            db.commit()
            return job_id
    finally:
        reset_parent_job(token)


def test_同样的要求接回上回那张单_不再下单() -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, child_id = _in_node(ws)
    assert _order_again(parent_id, dict(ASKED), lambda: pytest.fail("又下了一次单")) == child_id


def test_调整过参数的节点_旧单认不上_下新单() -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, _ = _in_node(ws)
    assert _order_again(parent_id, {"prompt": "晴天"}, lambda: "新单") == "新单"


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_失败或取消的单_重新下一张(status: str) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, _ = _in_node(ws, status)
    assert _order_again(parent_id, ASKED, lambda: "新单") == "新单"


def test_一个节点下的几张单各认各的_和走到它们的先后无关() -> None:
    """改口型那样的节点:第二遍时前面的块走了缓存不下单,后面的块不能认到第一块的单上。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, first = _in_node(ws)
    with SessionLocal() as db:
        chunk = Job(workspace_id=ws, kind="ai_generation", status="running")
        db.add(chunk)
        db.commit()
        chunk_id = chunk.id
    second = _order_again(parent_id, "第二块", lambda: chunk_id)
    assert _order_again(parent_id, "第二块", lambda: pytest.fail("又下了一次单")) == second
    assert _order_again(parent_id, ASKED, lambda: pytest.fail("又下了一次单")) == first


def test_一个事务里连下两张单_都记得住() -> None:
    from app.domain.jobs import reset_parent_job, set_parent_job

    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    parent_id, _ = _in_node(ws)
    token = set_parent_job(parent_id)
    try:
        with SessionLocal() as db, node_scope("画角度"):
            run_steps.hold(db, "正面", "单一")
            run_steps.hold(db, "侧面", "单二")
            db.commit()
            assert len(run_steps._row(db, parent_id, "", "画角度").held) == 2
    finally:
        reset_parent_job(token)


def test_节点里等子任务的地方都认得出上回的单() -> None:
    """等子任务的节点要是自己下单不记账,断了再接着跑就是第二次付钱 —— 新节点照这里的样子走 run_steps。"""
    #: 解析文档认的是素材上那条进行中的解析,不用另外记。
    exempt = {"document_to_markdown"}
    missing = []
    for path in Path(subjobs.__file__).parent.glob("*.py"):
        if path.name == "common.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.FunctionDef) or node.name in exempt:
                continue
            calls = {sub.id for sub in ast.walk(node) if isinstance(sub, ast.Name)}
            if "wait_for_job" in calls and "run_steps" not in calls:
                missing.append(f"{path.name}:{node.name}")
    assert not missing, missing
