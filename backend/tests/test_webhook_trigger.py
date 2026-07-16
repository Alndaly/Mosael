from __future__ import annotations

import time

from tests.util import fresh_client


def test_webhook_trigger_flow() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "钩子流", "graph": {
            "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}],
            "edges": [],
        }},
    ).json()

    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "钩子任务",
            "kind": "workflow",
            "trigger_type": "webhook",
            "schedule": {},
            "payload": {"workflow_id": workflow["id"], "params": {}},
        },
    ).json()
    secret = task["payload"]["webhook_secret"]
    assert secret  # 创建时服务端自动生成

    # 错误密钥 → 403;webhook 路由不需要登录态
    anonymous = client
    bad = anonymous.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret=wrong")
    assert bad.status_code == 403

    fired = anonymous.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret={secret}")
    assert fired.status_code == 200, fired.text
    job_id = fired.json()["job_id"]

    deadline = time.monotonic() + 10
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert status == "succeeded"

    # 非 webhook 任务不接受钩子触发
    manual = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "手动任务",
            "kind": "workflow",
            "trigger_type": "manual",
            "schedule": {},
            "payload": {"workflow_id": workflow["id"], "params": {}},
        },
    ).json()
    refused = anonymous.post(f"/api/hooks/scheduled-tasks/{manual['id']}?secret=whatever")
    assert refused.status_code == 403
