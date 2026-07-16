from __future__ import annotations

import time

from tests.util import fresh_client, second_client


def test_notification_read_flow() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    # 工作流失败是通知的标准生产者:code 节点抛错 → 通知落库
    workflow = client.post(
        "/api/workflows",
        json={"workspace_id": ws["id"], "name": "会失败的流", "graph": {
            "nodes": [
                {"id": "start", "type": "start", "config": {"params": {}}},
                {"id": "boom", "type": "code", "config": {"code": "raise RuntimeError('炸了')"}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "boom"}],
        }},
    ).json()
    run = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}})
    assert run.status_code == 200, run.text
    job_id = run.json()["id"]

    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "failed"

    listing = client.get(f"/api/notifications?workspace_id={ws['id']}").json()
    assert listing["unread"] == 1
    item = listing["items"][0]
    assert item["type"] == "workflow"
    assert "会失败的流" in item["title"]
    assert item["link"] == "#/workflows"
    assert item["read_at"] is None

    # 单条已读 → unread 归零;read-all 幂等
    read = client.post(f"/api/notifications/{item['id']}/read")
    assert read.status_code == 200
    assert read.json()["read_at"] is not None
    listing = client.get(f"/api/notifications?workspace_id={ws['id']}").json()
    assert listing["unread"] == 0
    assert client.post(f"/api/notifications/read-all?workspace_id={ws['id']}").json()["read"] == 0


def test_notification_scoped_to_user() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    other = second_client()

    # 其他用户不是工作区成员:访问被拒,也收不到通知
    denied = other.get(f"/api/notifications?workspace_id={ws['id']}")
    assert denied.status_code in (403, 404)
