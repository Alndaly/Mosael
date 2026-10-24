"""内容形状(ADR 0076):一条发布不只可能是视频。

这一版先把**数据和校验**立起来:平台声明自己能发哪几种形状(image-text / article),任务记下
`content_kind` 与多份素材 `asset_ids`,正文进 `body`;老数据靠默认值不必迁移。

测试钉三件事:
1. 注册表与 `contracts/platform-contracts.json`(真机核对的图数上限)**不能各说各的**;
2. `start_publish` 真的按平台声明拦(不认的形状、超张数、视频带多份);
3. 读的一侧对老任务有回退(`asset_ids` 为空 → `[asset_id]`),不然老记录会显示成「零份素材」。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import PublishTask
from app.domain.publish import CONTENT_KINDS, PUBLISH_PLATFORMS, content_limits, content_kinds
from tests.util import create_asset, fresh_client, make_video_asset

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "platform-contracts.json"


def _client():
    return fresh_client()


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _account(client, workspace_id: str, platform: str) -> dict:
    response = client.post(
        "/api/publish/accounts",
        json={"workspace_id": workspace_id, "platform": platform, "name": f"{platform}-1", "config": {}},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _image(client, workspace_id: str, name: str) -> dict:
    return create_asset(
        client,
        {"workspace_id": workspace_id, "kind": "image", "name": name, "file_key": f"media/test-publish/{name}.jpg"},
    )


def test_every_declared_kind_is_one_of_the_three_real_shapes() -> None:
    for platform, meta in PUBLISH_PLATFORMS.items():
        declared = tuple(meta.get("kinds") or ("video",))
        assert declared, platform
        assert set(declared) <= set(CONTENT_KINDS), f"{platform} 声明了不存在的形状"
        assert "video" in declared, f"{platform} 连视频都不认了?这不会是真的"
        for kind in declared:
            if kind == "video":
                continue
            #: 没核实过的上限允许是 None(B 站动态的图片张数就是这种);声明了就必须是正数。
            limit = content_limits(platform, kind).get("max_items")
            assert limit is None or limit > 0, platform


def test_image_limits_match_the_verified_platform_contract() -> None:
    """真机核对的上限只有一份事实:契约文件与后端注册表不能漂。"""
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for platform, value in contract["platforms"].items():
        image_max = value["limits"].get("imageMax")
        if image_max is None:
            continue
        backend_max = content_limits(platform, "image-text").get("max_items")
        assert backend_max == image_max, (
            f"{platform}: 契约写 {image_max} 张,后端注册表写 {backend_max} —— 两份会漂"
        )


def test_a_platform_that_has_no_article_shape_says_so() -> None:
    """文章形态是按平台真机核过的。

    X 的 Articles 入口 2026-10-24 找到了(`x.com/compose/articles` 的「Write」新建草稿),
    所以现在**声明** article;YouTube 仍然没有(Studio 里没有社区帖 / 长文入口)。"""
    assert "article" in content_kinds("x")  # Articles:编辑端点「Write」新建
    assert "article" not in content_kinds("youtube")
    assert "article" in content_kinds("xiaohongshu")  # 写长文(标题 64)
    assert "article" in content_kinds("douyin")  # 发布文章(正文 20000)


def test_image_text_task_keeps_every_asset_in_order() -> None:
    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "xiaohongshu")
    first = _image(client, workspace_id, "封面")
    second = _image(client, workspace_id, "第二张")

    response = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "content_kind": "image-text",
            "asset_ids": [first["id"], second["id"]],
            "title": "一条笔记",
            "body": "正文写在这里",
            "description": "",
            "tags": ["测试"],
        },
    )
    assert response.status_code == 200, response.text
    task = response.json()
    assert task["content_kind"] == "image-text"
    assert task["asset_ids"] == [first["id"], second["id"]]
    assert task["body"] == "正文写在这里"
    #: 第一份仍写进 asset_id —— 老读者(列表、作品查询)不用改。
    assert task["asset_id"] == first["id"]


def test_xiaohongshu_refuses_more_than_eighteen_images() -> None:
    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "xiaohongshu")
    ids = [_image(client, workspace_id, f"图{i}")["id"] for i in range(19)]

    response = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "content_kind": "image-text",
            "asset_ids": ids,
            "title": "太多了",
        },
    )
    assert response.status_code == 422
    assert "18" in response.text


def test_a_kind_the_platform_does_not_accept_is_refused_before_creating_anything() -> None:
    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "youtube")
    image = _image(client, workspace_id, "图")

    response = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "content_kind": "article",
            "asset_ids": [image["id"]],
            "title": "文章",
        },
    )
    assert response.status_code == 422
    assert client.get(f"/api/publish/tasks?workspace_id={workspace_id}").json() == []


def test_video_is_still_exactly_one_asset() -> None:
    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "douyin")
    one = make_video_asset(client, workspace_id)
    two = make_video_asset(client, workspace_id)

    response = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "content_kind": "video",
            "asset_ids": [one["id"], two["id"]],
            "title": "两条视频",
        },
    )
    assert response.status_code == 422


def test_a_body_over_the_platform_limit_is_refused() -> None:
    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "xiaohongshu")
    image = _image(client, workspace_id, "图")

    response = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "content_kind": "image-text",
            "asset_ids": [image["id"]],
            "title": "超长",
            "body": "字" * 1001,
        },
    )
    assert response.status_code == 422
    assert "1000" in response.text


def test_the_migration_backfills_the_single_asset_and_the_kind() -> None:
    """**形状由迁移统一,不靠运行时回退**。

    这一条此前测的是"读的一侧在 asset_ids 为空时回退到 [asset_id]" —— 那条回退让"老形状"永远
    活着。现在改成测迁移:空 asset_ids + 空 content_kind 的行,迁移后被填成「一份素材 / video」,
    而运行时只认库里那两个字段。
    """
    from app.db.migrations import _migrate_publish_tasks_get_content_shape

    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "douyin")
    asset = make_video_asset(client, workspace_id)
    created = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "asset_ids": [asset["id"]],
            "content_kind": "video",
            "title": "老形状",
        },
    ).json()

    with SessionLocal() as db:
        task = db.get(PublishTask, created["id"])
        #: 模拟迁移之前落下的那一行。
        task.asset_ids = []
        task.content_kind = ""
        db.commit()

    _migrate_publish_tasks_get_content_shape()

    with SessionLocal() as db:
        task = db.get(PublishTask, created["id"])
        assert task.asset_ids == [asset["id"]]
        assert task.content_kind == "video"


def test_the_worker_gets_every_asset_in_order_and_the_content_shape() -> None:
    """执行器认领时拿到的是**全部**素材(按顺序)与内容形状 —— 它按 kind 挑上传方法。"""
    from tests.util import worker_client

    client = _client()
    workspace_id = _workspace(client)
    account = _account(client, workspace_id, "xiaohongshu")
    first = _image(client, workspace_id, "封面")
    second = _image(client, workspace_id, "第二张")
    task = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "content_kind": "image-text",
            "asset_ids": [first["id"], second["id"]],
            "title": "一条笔记",
            "body": "正文",
        },
    ).json()

    worker = worker_client()
    claimed = worker.post("/api/publish/worker/claim", json={"worker": "w1", "exclude_accounts": []})
    assert claimed.status_code == 200, claimed.text
    payload = claimed.json()
    assert payload["task"]["id"] == task["id"]
    handed = payload["task"]
    assert handed["content_kind"] == "image-text"
    assert handed["body"] == "正文"
    assert len(handed["media_paths"]) == 2
    #: **只有一种形状**:`media_paths`(按顺序)。协议里不再有 `video_path` —— 视频就是第一个。
    assert "video_path" not in handed
