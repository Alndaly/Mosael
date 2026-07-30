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


def test_workflow_delivery_node(tmp_path: Path) -> None:
    """工作流里「送到本地目录」走 delivery 节点。

    以前它走 publish 节点 + 一个 platform=folder 的「发布账号」。folder 拆到交付域之后,
    分派留在节点层:用户选 publish 还是 delivery,数据模型上不再有 executor 这种岔路。
    """
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = make_video_asset(client, ws["id"])
    target = client.post(
        "/api/delivery/targets",
        json={
            "workspace_id": ws["id"],
            "kind": "folder",
            "name": "工作流交付",
            "config": {"directory": str(tmp_path / "wf-out")},
        },
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
                        "type": "delivery",
                        "config": {
                            "target_id": target["id"],
                            "asset_id": "{{start.asset}}",
                            "title": "工作流交付",
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

    tasks = client.get(f"/api/delivery/tasks?workspace_id={ws['id']}").json()
    assert tasks[0]["title"] == "工作流交付"
    assert tasks[0]["status"] == "succeeded"
