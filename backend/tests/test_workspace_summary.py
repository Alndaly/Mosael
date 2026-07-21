"""首页仪表聚合端点:单请求给全一屏统计。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Job, Project, PublishAccount, PublishTask, Sequence, Workflow
from tests.util import fresh_client


def test_summary_counts_scoped_to_the_workspace() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "W2"}).json()["id"]

    with SessionLocal() as db:
        project = Project(workspace_id=ws, name="P")
        db.add(project)
        db.flush()
        asset = Asset(workspace_id=ws, name="a", kind="video")
        db.add(asset)
        db.add(Asset(workspace_id=other, name="foreign", kind="video"))  # 不该被计入
        db.add(Sequence(workspace_id=ws, project_id=project.id, name="S"))
        db.add(Workflow(workspace_id=ws, name="wf", graph={"nodes": [], "edges": []}))
        db.add(Job(workspace_id=ws, kind="render", status="running", payload={}))
        db.add(Job(workspace_id=ws, kind="render", status="succeeded", payload={}))
        account = PublishAccount(workspace_id=ws, platform="mock", name="acc", config={})
        db.add(account)
        db.flush()
        db.add(
            PublishTask(
                workspace_id=ws, account_id=account.id, asset_id=asset.id, title="t",
                description="", tags=[], status="success",
            )
        )
        db.commit()

    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    assert summary["project_count"] == 1
    assert summary["asset_count"] == 1  # 邻工作区素材不计入
    assert summary["sequence_count"] == 1
    assert summary["workflow_count"] == 1
    assert summary["running_jobs"] == 1
    assert summary["week_jobs_succeeded"] == 1
    assert summary["week_jobs_failed"] == 0
    assert summary["publish_accounts"] == 1
    assert summary["week_published"] == 1
    assert summary["kb_document_count"] == 0


def test_summary_of_a_foreign_workspace_is_404() -> None:
    from tests.util import second_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    stranger = second_client()
    assert stranger.get(f"/api/workspaces/{ws}/summary").status_code == 404
