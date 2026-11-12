"""管理台:用户资料编辑/删除,套餐删除。"""

from __future__ import annotations

from sqlalchemy import select

from cloud.domain import admin as role_admin
from cloud.models import CloudUser
from conftest import PASSWORD, api, login, signup


def _make_admin(client, email: str = "admin@example.com") -> str:
    signup(client, email=email, password=PASSWORD)
    with client.app.state.db.session() as db:
        user = db.scalar(select(CloudUser).where(CloudUser.email == email))
        role_admin.grant(db, user)
        db.commit()
        return user.id


def _user_id(client, email: str) -> str:
    with client.app.state.db.session() as db:
        return db.scalar(select(CloudUser.id).where(CloudUser.email == email))


def test_admin_edits_public_identity_and_deletes_a_member(client):
    _make_admin(client)
    signup(client, email="member@example.com", password=PASSWORD)
    login(client, email="admin@example.com", password=PASSWORD)
    member_id = _user_id(client, "member@example.com")

    updated = client.patch(api(f"/admin/users/{member_id}"), json={"display_name": "新名字", "handle": "new-name"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["user"]["display_name"] == "新名字"
    assert updated.json()["user"]["handle"] == "new-name"

    deleted = client.delete(api(f"/admin/users/{member_id}"))
    assert deleted.status_code == 204, deleted.text
    assert client.get(api(f"/admin/users/{member_id}")).status_code == 404


def test_ip_ban_blocks_non_admin_api_but_not_unban(client):
    _make_admin(client)
    banned = client.post(api("/admin/ip-bans"), json={"ip": "203.0.113.9", "reason": "abuse"})
    assert banned.status_code == 201, banned.text
    blocked = client.get(api("/plans"), headers={"X-Forwarded-For": "203.0.113.9"})
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "ip_banned"
    # 管理端仍可达,否则管理员无法解封。
    assert client.get(api("/admin/ip-bans")).status_code == 200
    assert client.delete(api("/admin/ip-bans/203.0.113.9")).status_code == 204
    assert client.get(api("/plans"), headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 200


def test_banning_blocks_login_and_unban_restores_it(client):
    _make_admin(client)
    signup(client, email="banned@example.com", password=PASSWORD)
    user_id = _user_id(client, "banned@example.com")
    login(client, email="admin@example.com", password=PASSWORD)

    banned = client.post(api(f"/admin/users/{user_id}/ban"), json={"reason": "abuse"})
    assert banned.status_code == 200, banned.text
    assert banned.json()["user"]["banned"] is True

    blocked = client.post(api("/login"), json={"email": "banned@example.com", "password": PASSWORD})
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "account_banned"

    assert client.post(api(f"/admin/users/{user_id}/unban")).status_code == 200
    restored = client.post(api("/login"), json={"email": "banned@example.com", "password": PASSWORD})
    assert restored.status_code == 200, restored.text


def test_admin_can_increase_and_decrease_user_credits(client):
    _make_admin(client)
    signup(client, email="credits@example.com", password=PASSWORD)
    login(client, email="admin@example.com", password=PASSWORD)
    user_id = _user_id(client, "credits@example.com")

    added = client.post(api(f"/admin/users/{user_id}/credits/adjust"), json={"delta": 100, "days": 30})
    assert added.status_code == 200, added.text
    assert added.json()["user"]["credits"] == 100

    removed = client.post(api(f"/admin/users/{user_id}/credits/adjust"), json={"delta": -40, "days": 30})
    assert removed.status_code == 200, removed.text
    assert removed.json()["user"]["credits"] == 60

    too_much = client.post(api(f"/admin/users/{user_id}/credits/adjust"), json={"delta": -999, "days": 30})
    assert too_much.status_code == 400
    assert too_much.json()["error"] == "insufficient_credits"


def test_admin_cannot_delete_self_or_official_account(client):
    admin_id = _make_admin(client)
    assert client.delete(api(f"/admin/users/{admin_id}")).status_code == 400

    with client.app.state.db.session() as db:
        official = CloudUser(id="official-user", email="official@example.com", official=True)
        db.add(official)
        db.commit()
    response = client.delete(api("/admin/users/official-user"))
    assert response.status_code == 409
    assert response.json()["error"] == "official_account"


def test_a_plan_without_references_can_be_deleted_but_an_in_use_one_cannot(client):
    _make_admin(client)
    created = client.post(api("/admin/plans"), json={
        "slug": "starter", "name": "Starter", "period": "month",
        "monthly_credits": 100, "credit_ttl_days": 30, "on_sale": True, "price_cents": 900,
    })
    assert created.status_code == 201, created.text
    assert client.delete(api("/admin/plans/starter")).status_code == 204

    again = client.post(api("/admin/plans"), json={
        "slug": "pro", "name": "Pro", "period": "month",
        "monthly_credits": 1000, "credit_ttl_days": 30, "on_sale": True, "price_cents": 2900,
    })
    assert again.status_code == 201, again.text
    signup(client, email="sub@example.com", password=PASSWORD)
    user_id = _user_id(client, "sub@example.com")
    login(client, email="admin@example.com", password=PASSWORD)
    subscribed = client.post(api(f"/admin/users/{user_id}/subscriptions"), json={"plan": "pro"})
    assert subscribed.status_code == 200, subscribed.text
    # 有订阅的套餐软删除:历史订阅保留,但不再列出、不能再买。
    assert client.delete(api("/admin/plans/pro")).status_code == 204
    assert all(one["slug"] != "pro" for one in client.get(api("/admin/plans")).json()["plans"])
    assert client.get(api(f"/admin/users/{user_id}")).json()["user"]["credits"] >= 1000
