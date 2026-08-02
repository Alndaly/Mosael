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


def test_agent_can_push_a_notification() -> None:
    """智能体的 notify_workspace 落在这条端点上。

    工作流的「发送通知」节点一直能做这件事,而对话里做不到 —— 用户让智能体跑一件长活、
    自己走开,回来时应该有一条通知等着,和工作流跑完时一样。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    created = client.post(
        "/api/notifications",
        json={"workspace_id": ws["id"], "title": "渲染完成", "body": "成片已导出"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["type"] == "agent"

    listing = client.get(f"/api/notifications?workspace_id={ws['id']}").json()
    assert listing["unread"] == 1
    assert listing["items"][0]["title"] == "渲染完成"
    assert listing["items"][0]["body"] == "成片已导出"


def test_agent_notification_respects_workspace_boundary() -> None:
    """不是这个工作区的成员,就不能往里推通知 —— 否则它成了给任意人发消息的通道。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    outsider = second_client("outsider")
    denied = outsider.post("/api/notifications", json={"workspace_id": ws["id"], "title": "喂"})
    assert denied.status_code in (403, 404), denied.text


def test_未知的通知类型当场报错() -> None:
    """NOTIFICATION_TYPES 以前是摆设:没人拿它校验,加一个新类型它一声不吭,
    而前端按 type 查图标表 —— 表里没有就退化成通用铃铛,看着正常其实没人认领。"""
    import pytest

    from app.core.db import SessionLocal
    from app.domain.notifications import notify

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="未知的通知类型"):
            notify(db, ws["id"], type="还没定义的类型", title="x")
