"""部署默认模型:管理员在界面上设得了,而且设完看得见。

它是必要的一层 —— 取默认模型**没有**「随便挑一个」的兜底(见 provider_models.resolve_default),
所以新人的起点必须有人替他回答,那个人就是部署管理员。此前它只能经 API 置位、没有任何界面,
而一个没有界面的能力不是功能,是隐藏状态。

这里守的是整条链:读得到(/api/admin/provider-defaults)、设得上(for_deployment=true 落在
owner_user_id="" 那一行)、别人的默认没被顺手改掉、以及**普通成员设不了**。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from tests.util import add_provider, fresh_client, second_client


def _provider(username: str = "tester"):
    with SessionLocal() as db:
        profile = add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"], owner_username=username,
            make_default=False,  # 这里要测的正是「设默认」,不能让脚手架先替它设好
        )
        db.commit()
        return profile.id


def test_an_admin_can_set_it_and_read_it_back() -> None:
    admin = fresh_client()
    profile_id = _provider()

    saved = admin.put(
        "/api/settings/provider-defaults/chat",
        json={"provider_profile_id": profile_id, "model": "m", "for_deployment": True},
    )
    assert saved.status_code == 200, saved.text

    listed = admin.get("/api/admin/provider-defaults")
    assert listed.status_code == 200, listed.text
    chat = next(row for row in listed.json() if row["capability"] == "chat")
    assert chat["provider_profile_id"] == profile_id
    assert chat["model"] == "m"


def test_setting_the_deployment_one_does_not_touch_my_own() -> None:
    """两行是分开的:部署那行是「还没设过的人」的起点,不是所有人的强制值。"""
    admin = fresh_client()
    profile_id = _provider()

    admin.put(
        "/api/settings/provider-defaults/chat",
        json={"provider_profile_id": profile_id, "model": "m", "for_deployment": True},
    )

    mine = admin.get("/api/settings/provider-defaults").json()
    chat = next(row for row in mine if row["capability"] == "chat")
    assert chat["is_mine"] is False, "设部署默认不该顺手把它变成我自己的选择"


def test_an_ordinary_member_cannot_set_it() -> None:
    fresh_client()
    profile_id = _provider()
    mate = second_client("mate")

    denied = mate.put(
        "/api/settings/provider-defaults/chat",
        json={"provider_profile_id": profile_id, "model": "m", "for_deployment": True},
    )
    assert denied.status_code == 403, denied.text


def test_an_ordinary_member_cannot_even_read_the_admin_list() -> None:
    """藏起来的入口不是权限 —— 前端据此决定显不显示,后端各自把关。"""
    fresh_client()
    mate = second_client("mate")

    assert mate.get("/api/admin/provider-defaults").status_code == 403
