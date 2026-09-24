"""外部系统凭触发密钥**跟进**它触发的那次运行:查进度、取消;密钥泄漏了能重置。

此前 webhook 只有触发一个口子:外部系统点了就只能干等,既不知道跑完没有,也停不下来 ——
查进度和取消的接口都要登录,而外部系统手上只有这把密钥。
"""
from __future__ import annotations

import time

from app.core.db import SessionLocal
from app.db.models import Job, ScheduledTaskRun
from tests.util import fresh_client


def _hooked(client, *, slow: bool = False):
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "钩子流", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}}).json()
    task = client.post("/api/scheduled-tasks", json={
        "workspace_id": ws["id"], "name": "钩子任务", "kind": "workflow", "trigger_type": "webhook",
        "schedule": {}, "payload": {"workflow_id": workflow["id"], "params": {}},
    }).json()
    return ws, workflow, task


def _wait(client, url: str) -> dict:
    deadline = time.monotonic() + 10
    body = client.get(url).json()
    while body["status"] not in ("succeeded", "failed", "cancelled") and time.monotonic() < deadline:
        time.sleep(0.2)
        body = client.get(url).json()
    return body


def test_an_external_caller_can_follow_the_run_it_fired() -> None:
    client = fresh_client()
    _, _, task = _hooked(client)
    secret = task["payload"]["webhook_secret"]
    base = f"/api/hooks/scheduled-tasks/{task['id']}"
    fired = client.post(f"{base}?secret={secret}").json()

    status_url = f"{base}/runs/{fired['run_id']}?secret={secret}"
    first = client.get(status_url, headers={"Accept-Language": "en-US"})
    assert first.status_code == 200, first.text
    assert first.json()["run_id"] == fired["run_id"] and first.json()["job_id"] == fired["job_id"]
    done = _wait(client, status_url)
    assert done["status"] == "succeeded" and done["progress"] == 1

    # 密钥不对 / 不是这个任务的运行:一律不给看。
    assert client.get(f"{base}/runs/{fired['run_id']}?secret=wrong").status_code == 403
    assert client.get(f"{base}/runs/nope?secret={secret}").status_code == 404
    # 已经结束的运行取消不了,说清楚是为什么。
    assert client.post(f"{base}/runs/{fired['run_id']}/cancel?secret={secret}").status_code == 409


def test_cancel_stops_a_run_that_is_still_going() -> None:
    client = fresh_client()
    ws, _, task = _hooked(client)
    secret = task["payload"]["webhook_secret"]
    base = f"/api/hooks/scheduled-tasks/{task['id']}"
    # 直接造一条「还在跑」的运行:真去触发的话,测试环境里起始节点一眨眼就跑完了,来不及取消。
    with SessionLocal() as db:
        job = Job(workspace_id=ws["id"], kind="workflow", status="running", progress=0.4, payload={}, result={})
        db.add(job)
        db.flush()
        run = ScheduledTaskRun(scheduled_task_id=task["id"], job_id=job.id, status="running")
        db.add(run)
        db.commit()
        run_id = run.id
    going = client.get(f"{base}/runs/{run_id}?secret={secret}").json()
    assert going["status"] == "running" and going["progress"] == 0.4
    r = client.post(f"{base}/runs/{run_id}/cancel?secret={secret}")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"  # 不是 failed:「我自己停掉的」和「跑挂了」要分得开
    assert client.get(f"{base}/runs/{run_id}?secret={secret}").json()["status"] == "cancelled"


def test_a_run_of_another_task_is_not_reachable_with_this_secret() -> None:
    """一把泄漏的密钥不能拿着猜来的 run_id 去看、去停**别的**任务。"""
    client = fresh_client()
    _, _, mine = _hooked(client)
    _, _, other = _hooked(client)
    theirs = client.post(f"/api/hooks/scheduled-tasks/{other['id']}?secret={other['payload']['webhook_secret']}").json()
    secret = mine["payload"]["webhook_secret"]
    base = f"/api/hooks/scheduled-tasks/{mine['id']}/runs/{theirs['run_id']}"
    assert client.get(f"{base}?secret={secret}").status_code == 404
    assert client.post(f"{base}/cancel?secret={secret}").status_code == 404


def test_resetting_the_secret_retires_the_old_url_and_edits_cannot_bring_it_back() -> None:
    client = fresh_client()
    _, workflow, task = _hooked(client)
    old = task["payload"]["webhook_secret"]
    rotated = client.post(f"/api/scheduled-tasks/{task['id']}/webhook-secret")
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()["payload"]["webhook_secret"]
    assert new and new != old
    base = f"/api/hooks/scheduled-tasks/{task['id']}"
    assert client.post(f"{base}?secret={old}").status_code == 403

    # 编辑时带着那份旧 payload 保存 —— 旧密钥不能借这条路回来,也不能自己指定一个。
    stale = {"workflow_id": workflow["id"], "params": {}, "webhook_secret": old}
    saved = client.patch(f"/api/scheduled-tasks/{task['id']}", json={"payload": stale}).json()
    assert saved["payload"]["webhook_secret"] == new
    assert client.post(f"{base}?secret={old}").status_code == 403
    assert client.post(f"{base}?secret={new}").status_code == 200


def test_only_webhook_tasks_have_a_secret_to_reset() -> None:
    client = fresh_client()
    ws, workflow, _ = _hooked(client)
    manual = client.post("/api/scheduled-tasks", json={
        "workspace_id": ws["id"], "name": "手动", "kind": "workflow", "trigger_type": "manual",
        "schedule": {}, "payload": {"workflow_id": workflow["id"], "params": {}},
    }).json()
    assert client.post(f"/api/scheduled-tasks/{manual['id']}/webhook-secret").status_code == 422
