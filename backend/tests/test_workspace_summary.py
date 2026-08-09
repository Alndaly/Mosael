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
        account = PublishAccount(workspace_id=ws, platform="folder", name="acc", config={"directory": "/tmp/out"})
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
    assert summary["publish_daily"][-1]["succeeded"] == 1
    assert summary["publish_platforms"] == {"folder": 1}


def test_summary_of_a_foreign_workspace_is_404() -> None:
    from tests.util import second_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    stranger = second_client()
    assert stranger.get(f"/api/workspaces/{ws}/summary").status_code == 404


def test_summary_charts_daily_and_asset_kinds() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        db.add(Asset(workspace_id=ws, name="v", kind="video"))
        db.add(Asset(workspace_id=ws, name="a", kind="audio"))
        db.add(Job(workspace_id=ws, kind="render", status="succeeded", payload={}))
        db.add(Job(workspace_id=ws, kind="render", status="failed", payload={}))
        db.commit()

    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    assert len(summary["daily"]) == 14  # 缺日补零,长度恒定
    today = summary["daily"][-1]
    assert today["succeeded"] == 1 and today["failed"] == 1
    assert all(day["succeeded"] == 0 for day in summary["daily"][:-1])
    assert summary["asset_kinds"] == {"video": 1, "audio": 1}


def test_summary_publish_charts_group_statuses_and_platforms() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "W2"}).json()["id"]
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, name="v", kind="video")
        other_asset = Asset(workspace_id=other, name="ov", kind="video")
        db.add_all([asset, other_asset])
        acc_a = PublishAccount(workspace_id=ws, platform="douyin", name="dy", config={})
        acc_b = PublishAccount(workspace_id=ws, platform="bilibili", name="b", config={})
        acc_other = PublishAccount(workspace_id=other, platform="douyin", name="other", config={})
        db.add_all([acc_a, acc_b, acc_other])
        db.flush()
        for status, account in (
            ("success", acc_a),
            ("failed", acc_a),
            ("running", acc_b),
            ("login_required", acc_b),
        ):
            db.add(
                PublishTask(
                    workspace_id=ws,
                    account_id=account.id,
                    asset_id=asset.id,
                    title=status,
                    description="",
                    tags=[],
                    status=status,
                )
            )
        db.add(
            PublishTask(
                workspace_id=other,
                account_id=acc_other.id,
                asset_id=other_asset.id,
                title="foreign",
                description="",
                tags=[],
                status="success",
            )
        )
        db.commit()

    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    assert len(summary["publish_daily"]) == 14
    today = summary["publish_daily"][-1]
    assert today == {
        "date": today["date"],
        "succeeded": 1,
        "failed": 1,
        "active": 1,
        "blocked": 1,
    }
    assert all(
        day["succeeded"] == day["failed"] == day["active"] == day["blocked"] == 0
        for day in summary["publish_daily"][:-1]
    )
    assert summary["publish_platforms"] == {"bilibili": 2, "douyin": 2}
