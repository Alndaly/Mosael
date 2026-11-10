"""智能体做得了「做一部连续剧」这一路要的几件事(维护者:从官方模板新建工作流、接续中断的运行、为人物资产配嗓子、
并行运行、盯进度 —— 都应该给 Mosael 里的智能体补上)。

此前这些只在界面上点得到:模板库「添加」、运行历史「从中断处继续」、资产库里选音色;智能体只能整张手写图、一张卡跑
一次、拿 get_job 看一个进度数。这里用智能体的工具(mcp_server,和边车读的是同一份清单)走一遍。
"""

from __future__ import annotations

import time

import mcp_server
from app.core.db import SessionLocal
from app.db.models import Job, Workflow, WorkflowRunStep
from app.domain.jobs import TERMINAL_STATUSES
from tests.util import fresh_client, user_id


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _approve(client, card: dict) -> dict:
    approved = client.post(f"/api/confirmations/{card['confirmation_id']}/approve")
    assert approved.status_code == 200, approved.text
    shown = client.get(f"/api/confirmations/{card['confirmation_id']}").json()
    assert shown["status"] == "executed", shown
    return shown["result"]


def _simple_workflow(client, ws: str) -> str:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": "一场戏", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {"topic": ""}}},
                  {"id": "say", "type": "template", "name": "写一句", "config": {"template": "{{start.topic}}"}}],
        "edges": [{"id": "e", "source": "start", "target": "say"}]}}).json()["id"]


def _wait(job_id: str) -> Job:
    for _ in range(200):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in TERMINAL_STATUSES:
                db.expunge(job)
                return job
        time.sleep(0.05)
    raise AssertionError(f"{job_id} 没跑完")


def test_从官方模板新建工作流_卡上审的就是落库的那张() -> None:
    client = fresh_client()
    ws = _workspace(client)
    templates = {one["id"] for one in mcp_server.list_workflow_templates()}
    assert {"series_setup", "full_video_generation"} <= templates

    with mcp_server.calling_as(user_id=user_id(), requested_by="mcp"):
        card = mcp_server.create_workflow(name="长明灯 · 系列设定", template_id="series_setup", workspace_id=ws)
    created = _approve(client, card)
    assert created["template_id"] == "series_setup"
    with SessionLocal() as db:
        graph = db.get(Workflow, created["workflow_id"]).graph
    assert graph["meta"]["template_id"] == "series_setup"
    assert {"series_bible", "character_assets", "location_assets"} <= {node["id"] for node in graph["nodes"]}


def test_模板和手写的图只能二选一_认不出的模板当场说清有哪些() -> None:
    client = fresh_client()
    ws = _workspace(client)
    both = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "create_workflow", "requested_by": "pi",
        "payload": {"name": "x", "template_id": "series_setup", "graph": {"nodes": [], "edges": []}}})
    assert both.status_code == 422
    unknown = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "create_workflow", "requested_by": "pi",
        "payload": {"name": "x", "template_id": "no_such"}})
    assert unknown.status_code == 422 and "series_setup" in unknown.text


def test_一张卡并行起几次运行_各带一组参数_逐条看得到进度() -> None:
    client = fresh_client()
    ws = _workspace(client)
    wf = _simple_workflow(client, ws)
    with mcp_server.calling_as(user_id=user_id(), requested_by="mcp"):
        card = mcp_server.run_workflow(workflow_id=wf, workspace_id=ws,
                                       runs=[{"topic": "第一场"}, {"topic": "第二场"}, {"topic": "第三场"}])
    headline = client.get(f"/api/confirmations/{card['confirmation_id']}").json()["headline"]
    assert "3 次" in headline or "3 times" in headline, headline
    started = _approve(client, card)
    assert len(started["job_ids"]) == 3
    finished = [_wait(job_id) for job_id in started["job_ids"]]
    assert [job.status for job in finished] == ["succeeded"] * 3
    said = sorted(job.result["context"]["say"]["text"] for job in finished)
    assert said == ["第一场", "第三场", "第二场"]

    with mcp_server.calling_as(user_id=user_id(), requested_by="mcp"):
        progress = mcp_server.get_workflow_run(started["job_ids"][0])
    assert progress["status"] == "succeeded" and progress["steps_done"] == ["start", "写一句"]
    assert progress["steps_remaining"] == [] and progress["can_continue"] is False


def test_params_和_runs_只能给一个_一次最多八次() -> None:
    client = fresh_client()
    ws = _workspace(client)
    wf = _simple_workflow(client, ws)
    for payload in ({"params": {"topic": "a"}, "runs": [{"topic": "b"}]}, {"runs": [{"topic": str(i)} for i in range(9)]}):
        refused = client.post("/api/confirmations", json={
            "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi", "payload": {"workflow_id": wf, **payload}})
        assert refused.status_code == 422, refused.text


def test_中断的运行_智能体看得到停在哪_批准后从中断处接着跑() -> None:
    """做完的步骤记在 workflow_run_steps 里;把一次跑成功的运行改成「中断」、只留开始节点落定,接着跑只做剩下那一步。"""
    client = fresh_client()
    ws = _workspace(client)
    wf = _simple_workflow(client, ws)
    run = client.post(f"/api/workflows/{wf}/run", json={"params": {"topic": "雨夜"}}).json()
    _wait(run["id"])
    with SessionLocal() as db:
        job = db.get(Job, run["id"])
        job.status, job.message = "failed", "已中断"
        db.query(WorkflowRunStep).filter(WorkflowRunStep.job_id == job.id).delete()
        db.add(WorkflowRunStep(job_id=job.id, scope="", node_id="start", outputs={"topic": "雨夜"}))
        db.commit()

    with mcp_server.calling_as(user_id=user_id(), requested_by="mcp"):
        progress = mcp_server.get_workflow_run(run["id"])
        assert progress["steps_done"] == ["start"] and progress["steps_remaining"] == ["写一句"]
        assert progress["can_continue"] is True
        card = mcp_server.continue_workflow_run(run["id"])
    assert "「一场戏」" in client.get(f"/api/confirmations/{card['confirmation_id']}").json()["headline"]
    continued = _approve(client, card)
    assert continued["job_id"] == run["id"], "接着跑的是同一条运行"
    assert _wait(run["id"]).status == "succeeded"


def test_成功的运行不能接着跑() -> None:
    client = fresh_client()
    ws = _workspace(client)
    wf = _simple_workflow(client, ws)
    run = client.post(f"/api/workflows/{wf}/run", json={"params": {"topic": "x"}}).json()
    _wait(run["id"])
    refused = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "continue_workflow_run", "requested_by": "pi", "payload": {"job_id": run["id"]}})
    assert refused.status_code == 422


def test_给人物配嗓子_只收人物_空着是清掉() -> None:
    client = fresh_client()
    ws = _workspace(client)
    hero = client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": "沈青禾"}).json()
    shop = client.post("/api/entities", json={"workspace_id": ws, "kind": "location", "name": "长明灯铺"}).json()
    with mcp_server.calling_as(user_id=user_id(), requested_by="mcp"):
        voiced = mcp_server.set_entity_voice(hero["id"], engine="builtin:edge", voice="zh-CN-XiaoyiNeural")
        assert (voiced["attributes"]["voice"]["engine"], voiced["attributes"]["voice"]["voice"]) == (
            "builtin:edge", "zh-CN-XiaoyiNeural")
        cleared = mcp_server.set_entity_voice(hero["id"], engine="", voice="")
        assert not cleared["attributes"].get("voice")
        try:
            mcp_server.set_entity_voice(shop["id"], engine="builtin:edge", voice="zh-CN-XiaoyiNeural")
        except Exception as exc:  # noqa: BLE001 — 工具层把它翻成给模型看的一句
            assert "character" in str(exc)
        else:
            raise AssertionError("地点不该有嗓子")
