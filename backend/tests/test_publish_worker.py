from __future__ import annotations

from tests.test_publish import make_video_asset
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key
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
    # These tests drive the worker channel, which now needs its shared key.
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
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


def test_orphaned_running_task_is_reclaimed_on_fresh_claim() -> None:
    # 执行器认领后翻 running,若中途崩溃/重启丢了在飞任务,任务会永远停在"运行中"。
    # 下次轮询(claim)时应自愈:账号已不在 worker 在跑集合里 → 置 failed,可重试。
    client = fresh_client()
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
    ws, account, task = setup_browser_task(client)

    claimed = client.post("/api/publish/worker/claim", json={"exclude_accounts": []}).json()
    assert claimed["task"]["id"] == task["id"]
    assert client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()[0]["status"] == "running"

    # 账号仍在在跑集合里(worker 正常处理中)→ 不回收
    client.post("/api/publish/worker/claim", json={"exclude_accounts": [account["id"]]})
    assert client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()[0]["status"] == "running"

    # 执行器重启:在跑集合空了,这条 running 的 owner 已消失 → 自愈成 failed
    client.post("/api/publish/worker/claim", json={"exclude_accounts": []})
    healed = client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()[0]
    assert healed["status"] == "failed"
    assert "发布器中断" in (healed["error"] or "")
    assert client.get(f"/api/jobs/{task['job_id']}").json()["status"] == "failed"


def test_title_limit_and_binding_check_flow() -> None:
    client = fresh_client()
    # These tests drive the worker channel, which now needs its shared key.
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
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


def test_account_recheck_and_profile() -> None:
    client = fresh_client()
    # These tests drive the worker channel, which now needs its shared key.
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    account = client.post(
        "/api/publish/accounts",
        json={"workspace_id": ws["id"], "platform": "b站", "name": "B站矩阵一号", "config": {}},
    ).json()

    # worker 回报 bound + 平台昵称
    client.patch(
        "/api/publish/worker/account",
        json={"account_id": account["id"], "binding_status": "bound", "profile_name": "小美的频道"},
    )
    got = client.get(f"/api/publish/accounts?workspace_id={ws['id']}").json()[0]
    assert got["binding_status"] == "bound"
    assert got["profile_name"] == "小美的频道"
    assert got["last_checked_at"] is not None

    # 手动复检:归零登录态,等执行器下轮巡检认领
    rechecked = client.post(f"/api/publish/accounts/{account['id']}/recheck").json()
    assert rechecked["binding_status"] == "unknown"
    assert rechecked["last_checked_at"] is None
    claimed = client.post("/api/publish/worker/claim-check").json()
    assert claimed["account"]["account_id"] == account["id"]

    # 启停
    patched = client.patch(f"/api/publish/accounts/{account['id']}", json={"enabled": False}).json()
    assert patched["enabled"] is False
