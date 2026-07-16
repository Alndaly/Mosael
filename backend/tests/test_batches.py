from __future__ import annotations

import time

from tests.util import fresh_client


def wait_terminal(client, job_id: str, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            return status
        time.sleep(0.2)
    return status


def test_batch_runs_workflow_per_param_row() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post(
        "/api/workflows",
        json={
            "workspace_id": ws["id"],
            "name": "批量流",
            "graph": {
                "nodes": [
                    {"id": "start", "type": "start", "name": "开始", "config": {"params": {"topic": ""}}},
                    {
                        "id": "search",
                        "type": "kb_search",
                        "name": "查",
                        "config": {"query": "{{start.topic}}", "limit": 2},
                    },
                ],
                "edges": [{"id": "e1", "source": "start", "target": "search"}],
            },
        },
    ).json()

    created = client.post(
        "/api/batches",
        json={
            "workspace_id": ws["id"],
            "workflow_id": workflow["id"],
            "name": "三连发",
            "params_list": [{"topic": "海"}, {"topic": "山"}, {"topic": "城"}],
        },
    )
    assert created.status_code == 200, created.text
    batch = created.json()
    assert batch["status"] in ("queued", "running", "succeeded")
    assert len(batch["items"]) == 3

    assert wait_terminal(client, batch["job_id"]) == "succeeded"

    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert [item["status"] for item in detail["items"]] == ["succeeded"] * 3
    assert detail["progress"] == 1.0

    listed = client.get(f"/api/batches?workspace_id={ws['id']}").json()
    assert [b["name"] for b in listed] == ["三连发"]

    parent = client.get(f"/api/jobs/{batch['job_id']}").json()
    assert parent["result"] == {"succeeded": 3, "failed": 0, "total": 3}


def test_batch_item_failure_does_not_abort() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    # plugin_tool 指向不存在的插件 → 每次都会失败;混入一行合法 kb_search 无法
    # 在同一图里做,所以这里用"必失败"的图验证:批不中断、统计正确。
    workflow = client.post(
        "/api/workflows",
        json={
            "workspace_id": ws["id"],
            "name": "必失败流",
            "graph": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {"params": {}}},
                    {
                        "id": "boom",
                        "type": "plugin_tool",
                        "config": {"plugin_id": "ghost", "tool_name": "nope", "input": {}},
                    },
                ],
                "edges": [{"id": "e1", "source": "start", "target": "boom"}],
            },
        },
    ).json()

    batch = client.post(
        "/api/batches",
        json={
            "workspace_id": ws["id"],
            "workflow_id": workflow["id"],
            "name": "全灭",
            "params_list": [{}, {}],
        },
    ).json()

    assert wait_terminal(client, batch["job_id"]) == "failed"
    parent = client.get(f"/api/jobs/{batch['job_id']}").json()
    assert parent["result"] == {"succeeded": 0, "failed": 2, "total": 2}
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert [item["status"] for item in detail["items"]] == ["failed", "failed"]
    assert all(item["error"] for item in detail["items"])
