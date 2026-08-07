"""每一项设置属于谁:部署 / 工作区 / 人。

第 4 步把「连接」判成部署的、「钥匙」判成人的,但**没把同一把尺子量到底**。剩下的判错跑出来是:

    PUT /api/settings/provider-defaults/image   403 这项设置属于整个部署,只有部署管理员能改

「我默认用哪个模型」显然不是部署配置 —— 它和钥匙一样是个人偏好:两个人用同一条连接,完全
可以各自默认不同的模型。同一类错误还有几处:

  - 列某能力有哪些模型、列一条连接下的模型:**只读**。挡住它,普通人连"我要选哪个"都看不到。
  - 工作区的自动放行准则:那是**工作区**的规则,却要求部署管理员 —— 工作区 admin 管不了自己
    工作区的规则,说不通。

判据是同一句话:**这件事的后果落在谁身上。** 落在整台机器上(装东西、出网、连接怎么连)→ 部署;
落在这个工作区里 → 工作区;落在这个人自己头上(用谁的钥匙、默认用哪个模型)→ 人。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import User
from tests.util import fresh_client, second_client


def _admin_and_member() -> tuple[TestClient, TestClient, dict]:
    admin = fresh_client()
    workspace = admin.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    admin.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return admin, mate, workspace


def _connection(admin: TestClient, vendor: str = "openai") -> str:
    made = admin.post("/api/settings/providers", json={"name": "N", "vendor": vendor, "config": {}})
    assert made.status_code == 200, made.text
    return made.json()["id"]


# ---------------- 默认模型是**人**的 ----------------


def test_an_ordinary_member_can_set_their_own_default_model() -> None:
    """「我默认用哪个模型」是个人偏好,和钥匙一样。"""
    admin, mate, _workspace = _admin_and_member()
    profile_id = _connection(admin)
    admin.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": "gpt-image-2"})

    saved = mate.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": profile_id, "model": "gpt-image-2"},
    )
    assert saved.status_code == 200, saved.text


def test_my_default_is_mine_and_does_not_touch_anyone_else() -> None:
    admin, mate, _workspace = _admin_and_member()
    profile_id = _connection(admin)
    for model in ("gpt-image-2", "gpt-image-3"):
        admin.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": model})

    admin.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": profile_id, "model": "gpt-image-2"},
    )
    mate.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": profile_id, "model": "gpt-image-3"},
    )

    mine = {row["capability"]: row for row in admin.get("/api/settings/provider-defaults").json()}
    theirs = {row["capability"]: row for row in mate.get("/api/settings/provider-defaults").json()}
    assert mine["image"]["model"] == "gpt-image-2"
    assert theirs["image"]["model"] == "gpt-image-3", "他改默认模型改到了别人头上"


def test_a_newcomer_starts_with_nothing_chosen() -> None:
    """新人面对的是一排空下拉,而这是**对的**。

    曾经有一层部署默认给他当起点,删掉了:一个他没选过的模型替他回答,花的是他的额度、用的是
    他的钥匙。空下拉配上一句"先选一个"是能看懂的;悄悄替他选一个,他连发生了什么都不知道。
    """
    admin, mate, _workspace = _admin_and_member()
    profile_id = _connection(admin)
    admin.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": "gpt-image-2"})
    admin.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": profile_id, "model": "gpt-image-2"},
    )

    theirs = {row["capability"]: row for row in mate.get("/api/settings/provider-defaults").json()}
    assert theirs["image"]["model"] == "", "拿到了管理员的默认"
    assert theirs["image"]["is_mine"] is False


def test_setting_a_default_is_never_a_decision_for_everyone() -> None:
    """写默认永远只写自己那一条 —— 没有"替整个部署做决定"这条路了,所以也不需要更高的权限。"""
    admin, mate, _workspace = _admin_and_member()
    profile_id = _connection(admin)
    admin.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": "gpt-image-2"})

    allowed = mate.put(
        "/api/settings/provider-defaults/image",
        json={"provider_profile_id": profile_id, "model": "gpt-image-2"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["is_mine"] is True

    ours = {row["capability"]: row for row in admin.get("/api/settings/provider-defaults").json()}
    assert ours["image"]["model"] == "", "他设自己的默认设到了别人头上"


# ---------------- 只读的东西不该挡 ----------------


def test_anyone_can_see_which_models_exist() -> None:
    """挡住"有哪些模型可选",等于让人闭着眼睛选自己的默认。"""
    admin, mate, _workspace = _admin_and_member()
    profile_id = _connection(admin)
    admin.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": "gpt-image-2"})

    assert mate.get("/api/settings/capability-models/image").status_code == 200
    assert mate.get(f"/api/settings/providers/{profile_id}/models").status_code == 200


def test_an_ordinary_member_still_cannot_change_the_catalogue() -> None:
    """看得见不等于改得动:模型目录属于连接,连接是部署的配置。"""
    admin, mate, _workspace = _admin_and_member()
    profile_id = _connection(admin)
    denied = mate.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": "偷偷加一个"})
    assert denied.status_code == 403, denied.text


# ---------------- 工作区的规则归工作区 ----------------


def test_a_workspace_admin_owns_their_workspaces_autopilot_rules() -> None:
    """自动放行准则是**这个工作区**的规则,不是整台机器的。"""
    admin, mate, workspace = _admin_and_member()
    with SessionLocal() as db:
        person = db.query(User).filter(User.username == "mate").one()
        person_id = person.id
    admin.patch(f"/api/workspaces/{workspace['id']}/members/{person_id}", json={"role": "admin"})

    saved = mate.put(
        f"/api/workspaces/{workspace['id']}/autopilot-rules",
        json={"rules": {"http": {"deny": ["example.com"]}}},
    )
    assert saved.status_code == 200, saved.text


def test_an_editor_cannot_change_the_workspaces_autopilot_rules() -> None:
    """它决定"智能体能不问就做什么" —— 工作区级的决定,不是每个 editor 自己能改的。"""
    _admin, mate, workspace = _admin_and_member()
    denied = mate.put(
        f"/api/workspaces/{workspace['id']}/autopilot-rules",
        json={"rules": {"http": {"allow": ["example.com"]}}},
    )
    assert denied.status_code == 403, denied.text


# ---------------- 仍然是部署的那些 ----------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("put", "/api/settings/network", {"proxy_url": "http://127.0.0.1:1"}),
        ("post", "/api/settings/providers", {"name": "X", "vendor": "openai", "config": {}}),
        ("post", "/api/auth/invites", {}),
    ],
)
def test_these_really_are_deployment_wide(method: str, path: str, body: dict) -> None:
    """后果落在整台机器上的,仍然只有部署管理员能动:出网、连接怎么连、谁能进来。"""
    _admin, mate, _workspace = _admin_and_member()
    denied = getattr(mate, method)(path, json=body)
    assert denied.status_code == 403, f"{path} 不该让普通成员改:{denied.text}"
