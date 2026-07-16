from __future__ import annotations

from tests.test_publish import make_video_asset
from tests.util import fresh_client


def setup_browser_task(client) -> tuple[dict, dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])
    account = client.post(
        "/api/publish/accounts",
        json={"workspace_id": ws["id"], "platform": "抖音", "name": "主号", "config": {}},
    ).json()
    assert account["platform"] == "douyin"  # 别名归一化
    task = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": ws["id"],
            "account_id": account["id"],
            "asset_id": asset["id"],
            "title": "夏日海边三十秒混剪压在三十字以内",
            "description": "简介",
            "tags": ["海边"],
        },
    ).json()
    return ws, account, task


def test_browser_platform_waits_for_worker_and_reports() -> None:
    client = fresh_client()
    ws, account, task = setup_browser_task(client)

    # 浏览器平台不在进程内执行:任务保持 pending,job 等待认领
    listed = client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()
    assert listed[0]["status"] == "pending"

    # worker 认领(免鉴权通道)→ running,拿到绝对视频路径
    claimed = client.post("/api/publish/worker/claim", json={"exclude_accounts": []}).json()
    assert claimed["task"]["id"] == task["id"]
    assert claimed["task"]["platform"] == "douyin"
    assert claimed["task"]["video_path"].endswith("clip.mp4")

    # 同账号任务在 exclude 列表里 → 认领不到
    again = client.post("/api/publish/worker/claim", json={"exclude_accounts": [account["id"]]}).json()
    assert again["task"] is None

    # 中间富状态 → job 保持 running;终态 success → job succeeded
    client.patch(
        "/api/publish/worker/report",
        json={"task_id": task["id"], "status": "login_required", "error_message": "扫码登录"},
    )
    mid = client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()[0]
    assert mid["status"] == "login_required"
    job = client.get(f"/api/jobs/{task['job_id']}").json()
    assert job["status"] == "running"

    client.patch("/api/publish/worker/report", json={"task_id": task["id"], "status": "success"})
    done = client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()[0]
    assert done["status"] == "success"
    assert client.get(f"/api/jobs/{task['job_id']}").json()["status"] == "succeeded"


def test_title_limit_and_binding_check_flow() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])
    account = client.post(
        "/api/publish/accounts",
        json={"workspace_id": ws["id"], "platform": "视频号", "name": "小号", "config": {}},
    ).json()

    # 视频号 title_max=16,超长在创建时就拒
    too_long = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": ws["id"],
            "account_id": account["id"],
            "asset_id": asset["id"],
            "title": "这是一条明显超过十六个字上限的超长标题啊",
        },
    )
    assert too_long.status_code == 422
    assert "16" in too_long.json()["detail"]

    # 登录态巡检:认领 → checking → 回报 bound
    checked = client.post("/api/publish/worker/claim-check").json()
    assert checked["account"]["account_id"] == account["id"]
    client.patch(
        "/api/publish/worker/account",
        json={"account_id": account["id"], "binding_status": "bound"},
    )
    accounts = client.get(f"/api/publish/accounts?workspace_id={ws['id']}").json()
    assert accounts[0]["binding_status"] == "bound"

    # 全量巡检标记后可再次认领
    marked = client.post("/api/publish/worker/mark-due").json()
    assert marked["marked"] == 1

    # 心跳 → 在线状态
    client.post("/api/publish/worker/heartbeat")
    assert client.get("/api/publish/worker/status").json()["online"] is True
