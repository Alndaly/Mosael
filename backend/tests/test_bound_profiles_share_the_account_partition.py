"""绑定了发布账号的浏览器档案,分区必须是**那个账号的规范分区**。

现场(2026-10-22):同一个抖音账号有两份分区 —— 发布账号登录落在 `persist:mosael-<accountId>`
(真正的 sessionid 在那儿),而池档案还指着一个历史前缀 `persist:openstudio-<accountId>`
(只有 sid_guard 这类不认证的票据)。结果:账号池卡片显示「已登录」、点「打开」也是登录态,
但智能体经浏览器池开会话打开的是那份旧分区,平台让他登录。

`contracts/shared-constants.json` 的 `publish_partition_prefix` 警告过这件事:「改了前缀,所有
已登录的发布账号 cookie 会凭空消失,而且不会有任何报错」。
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_bound_profiles_use_the_account_partition
from tests.util import fresh_client


def _partition_of(profile_id: str) -> str:
    with engine.begin() as conn:
        return conn.execute(
            text('SELECT "partition" FROM browser_profiles WHERE id = :pid'), {"pid": profile_id}
        ).scalar_one()


def test_a_bound_profile_follows_its_account_partition() -> None:
    fresh_client()  # 建库 + 迁移
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    account = client.post(
        "/api/publish/accounts",
        json={"workspace_id": workspace["id"], "platform": "douyin", "name": "抖音", "config": {}},
    ).json()
    assert account.get("id"), f"建账号失败: {account}"
    with SessionLocal() as db:
        from app.db.models import PublishAccount

        profile_id = db.get(PublishAccount, account["id"]).profile_id
    assert profile_id, "发布账号应该挂着浏览器档案"
    canonical = f"persist:mosael-{account['id']}"
    assert _partition_of(profile_id) == canonical, "新建的档案本来就该指向规范分区"

    # 模拟历史前缀留在库里的那一行(openstudio-),再跑一次迁移。
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE browser_profiles SET "partition" = :part WHERE id = :pid'),
            {"part": f"persist:openstudio-{account['id']}", "pid": profile_id},
        )
    _migrate_bound_profiles_use_the_account_partition()
    assert _partition_of(profile_id) == canonical

    # 幂等:再跑一次不会变(也不该报错)。
    _migrate_bound_profiles_use_the_account_partition()
    assert _partition_of(profile_id) == canonical
