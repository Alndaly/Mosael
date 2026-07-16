from __future__ import annotations

import json
import time
from pathlib import Path

from app.core.config import settings
from tests.util import fresh_client


def make_video_asset(client, workspace_id: str) -> dict:
    """入库一个最小可发布素材(直接写文件,不跑 ffmpeg)。"""
    media = settings.media_dir / "test-publish"
    media.mkdir(parents=True, exist_ok=True)
    source = media / "clip.mp4"
    source.write_bytes(b"fake-video-bytes")
    created = client.post(
        "/api/assets",
        json={
            "workspace_id": workspace_id,
            "kind": "video",
            "name": "成片A",
            "file_key": "media/test-publish/clip.mp4",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def wait_status(client, job_id: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    status = "queued"
    while time.monotonic() < deadline:
        status = client.get(f"/api/jobs/{job_id}").json()["status"]
        if status in ("succeeded", "failed"):
            return status
        time.sleep(0.15)
    return status


def test_folder_publish_flow(tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])

    platforms = client.get("/api/publish/platforms").json()
    assert {item["platform"] for item in platforms} >= {"folder", "webhook", "mock"}

    # 缺必填配置 → 422
    bad = client.post(
        "/api/publish/accounts",
        json={"workspace_id": ws["id"], "platform": "folder", "name": "坏账号", "config": {}},
    )
    assert bad.status_code == 422

    out_dir = tmp_path / "out"
    account = client.post(
        "/api/publish/accounts",
        json={
            "workspace_id": ws["id"],
            "platform": "folder",
            "name": "本地交付",
            "config": {"directory": str(out_dir)},
        },
    ).json()

    task = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": ws["id"],
            "account_id": account["id"],
            "asset_id": asset["id"],
            "title": "夏日海边混剪",
            "description": "蓝色大海与晚霞。",
            "tags": ["海边", "旅行"],
        },
    )
    assert task.status_code == 200, task.text
    assert wait_status(client, task.json()["job_id"]) == "succeeded"

    listed = client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()
    assert listed[0]["status"] == "succeeded"
    target = Path(listed[0]["result"]["target"])
    assert target.exists() and target.read_bytes() == b"fake-video-bytes"
    sidecar = json.loads(Path(listed[0]["result"]["sidecar"]).read_text(encoding="utf-8"))
    assert sidecar["title"] == "夏日海边混剪"
    assert sidecar["tags"] == ["海边", "旅行"]


def test_workflow_publish_node(tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])
    account = client.post(
        "/api/publish/accounts",
        json={"workspace_id": ws["id"], "platform": "mock", "name": "演示", "config": {}},
    ).json()

    workflow = client.post(
        "/api/workflows",
        json={
            "workspace_id": ws["id"],
            "name": "发布流",
            "graph": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {"params": {"asset": asset["id"]}}},
                    {
                        "id": "pub",
                        "type": "publish",
                        "config": {
                            "account_id": account["id"],
                            "asset_id": "{{start.asset}}",
                            "title": "工作流发布",
                        },
                    },
                ],
                "edges": [{"id": "e1", "source": "start", "target": "pub"}],
            },
        },
    )
    assert workflow.status_code == 200, workflow.text

    run = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}})
    assert run.status_code == 200, run.text
    assert wait_status(client, run.json()["id"]) == "succeeded"

    publishes = client.get(f"/api/publish/tasks?workspace_id={ws['id']}").json()
    assert publishes[0]["title"] == "工作流发布"
    assert publishes[0]["status"] == "succeeded"
