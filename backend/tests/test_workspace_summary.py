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
    assert summary["jobs_succeeded"] == 1
    assert summary["jobs_failed"] == 0
    # `publish_accounts`(发布账号数)曾经也在这里 —— 界面一次都没读过,已删。
    assert summary["published"] == 1
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
    assert summary["window_days"] == 30  # 默认最近一个月
    assert len(summary["daily"]) == 30  # 缺日补零,长度就是窗口
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
    assert len(summary["publish_daily"]) == 30
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


def test_一个窗口管住读数_图和花费_总数不跟着窗口走() -> None:
    """读数和图此前一个是「近 7 天」、一个是「近 14 天」:同一页上两种窗口,两个数对不上。
    现在只有一个 `days`,任务、发布、平台构成、花费都按它算;项目、素材这些是当前总数。"""
    from datetime import timedelta

    from app.db.models import now

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, name="v", kind="video")
        account = PublishAccount(workspace_id=ws, platform="douyin", name="dy", config={})
        db.add_all([asset, account])
        db.flush()
        long_ago = now() - timedelta(days=20)
        db.add(Job(workspace_id=ws, kind="render", status="succeeded", payload={}))
        db.add(Job(workspace_id=ws, kind="render", status="failed", payload={}, updated_at=long_ago))
        db.add(
            PublishTask(
                workspace_id=ws, account_id=account.id, asset_id=asset.id, title="old",
                description="", tags=[], status="success", updated_at=long_ago,
            )
        )
        db.commit()

    week = client.get(f"/api/workspaces/{ws}/summary", params={"days": 7}).json()
    assert week["window_days"] == 7 and len(week["daily"]) == 7 and len(week["publish_daily"]) == 7
    assert (week["jobs_succeeded"], week["jobs_failed"], week["published"]) == (1, 0, 0)
    assert week["publish_platforms"] == {}  # 二十天前那一条不在这一周里
    assert week["asset_count"] == 1 and week["asset_kinds"] == {"video": 1}  # 总数不跟窗口走

    month = client.get(f"/api/workspaces/{ws}/summary", params={"days": 30}).json()
    assert (month["jobs_succeeded"], month["jobs_failed"], month["published"]) == (1, 1, 1)
    assert month["publish_platforms"] == {"douyin": 1}
    assert len(month["usage_daily"]) == 30  # 花费按同一个窗口

    assert client.get(f"/api/workspaces/{ws}/summary", params={"days": 91}).status_code == 422
