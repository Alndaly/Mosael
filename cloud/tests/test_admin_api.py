"""管理端 API:成员 / 角色 / 积分 / 套餐 / 模型目录。"""

from __future__ import annotations

from dataclasses import replace

import httpx2
from cryptography.fernet import Fernet
from sqlalchemy import select

from cloud.admin import service
from cloud.domain import admin as role_admin
from cloud.models import CloudGatewayCall, CloudGatewayModel, CloudUser
from conftest import PASSWORD, api, login, signup


def make_admin(client, email="admin@example.com"):
    signup(client, email=email, password=PASSWORD)
    with client.app.state.db.session() as db:
        user = db.scalar(select(CloudUser).where(CloudUser.email == email))
        role_admin.grant(db, user)
        db.commit()
    return user.id


def test_admin_overview_users_and_role_changes(client):
    make_admin(client)
    signup(client, email="member@example.com", password=PASSWORD)
    login(client, email="admin@example.com", password=PASSWORD)
    with client.app.state.db.session() as db:
        member_id = db.scalar(select(CloudUser.id).where(CloudUser.email == "member@example.com"))

    overview = client.get(api("/admin/overview"))
    assert overview.status_code == 200
    assert overview.json()["users"] == 2
    assert overview.json()["admins"] == 1

    users = client.get(api("/admin/users"), params={"q": "member"})
    assert users.status_code == 200
    assert users.json()["users"][0]["email"] == "member@example.com"

    promoted = client.post(api(f"/admin/users/{member_id}/role"), json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["user"]["role"] == "admin"

    demoted = client.post(api(f"/admin/users/{member_id}/role"), json={"role": "member"})
    assert demoted.status_code == 200
    assert demoted.json()["user"]["role"] == "member"

    events = client.get(api("/admin/audit")).json()["events"]
    assert [one["action"] for one in events[:2]] == ["user.role", "user.role"]
    assert events[0]["actor_email"] == "admin@example.com"
    assert "password" not in str(events).lower()


def test_last_admin_cannot_be_demoted(client):
    admin_id = make_admin(client)
    response = client.post(api(f"/admin/users/{admin_id}/role"), json={"role": "member"})
    assert response.status_code == 409
    assert response.json()["error"] == "last_admin"


def test_admin_can_reset_a_members_password_and_invalidates_sessions(client):
    make_admin(client)
    signup(client, email="reset@example.com", password=PASSWORD)
    login(client, email="admin@example.com", password=PASSWORD)
    with client.app.state.db.session() as db:
        customer_id = db.scalar(select(CloudUser.id).where(CloudUser.email == "reset@example.com"))

    reset = client.post(api(f"/admin/users/{customer_id}/reset-password"))
    assert reset.status_code == 200, reset.text
    temporary = reset.json()["temporary_password"]
    assert len(temporary) >= 8

    old = client.post(api("/login"), json={"email": "reset@example.com", "password": PASSWORD})
    assert old.status_code == 401
    fresh = client.post(api("/login"), json={"email": "reset@example.com", "password": temporary})
    assert fresh.status_code == 200, fresh.text
    login(client, email="admin@example.com", password=PASSWORD)

    with client.app.state.db.session() as db:
        db_user = db.scalar(select(CloudUser).where(CloudUser.email == "admin@example.com"))
        self_reset = client.post(api(f"/admin/users/{db_user.id}/reset-password"))
    assert self_reset.status_code == 400
    assert self_reset.json()["error"] == "cannot_reset_self"


def test_admin_can_gift_credits_and_subscribe(client):
    make_admin(client)
    signup(client, email="customer@example.com", password=PASSWORD)
    login(client, email="admin@example.com", password=PASSWORD)
    with client.app.state.db.session() as db:
        customer_id = db.scalar(select(CloudUser.id).where(CloudUser.email == "customer@example.com"))

    gift = client.post(api(f"/admin/users/{customer_id}/credits"), json={"credits": 100, "days": 30, "note": "test"})
    assert gift.status_code == 200, gift.text
    assert gift.json()["user"]["credits"] == 100

    plan = client.post(
        api("/admin/plans"),
        json={"slug": "pro", "name": "Pro", "period": "month", "monthly_credits": 200, "credit_ttl_days": 60, "on_sale": False},
    )
    assert plan.status_code == 201, plan.text
    subscribed = client.post(api(f"/admin/users/{customer_id}/subscriptions"), json={"plan": "pro"})
    assert subscribed.status_code == 200, subscribed.text
    assert subscribed.json()["user"]["subscription"]["plan"] == "pro"
    assert subscribed.json()["user"]["credits"] > 100


def test_admin_can_build_a_model_catalog_and_price(client):
    make_admin(client)
    created = client.post(
        api("/admin/models"),
        json={"id": "deepseek-chat", "label": "DeepSeek V3", "max_output_tokens": 8000, "sort_order": 1},
    )
    assert created.status_code == 201, created.text
    assert created.json()["model"]["listed"] is False
    assert created.json()["model"]["not_listed_reasons"] == ["missing_price", "missing_channel"]

    priced = client.post(api("/admin/models/deepseek-chat/prices"), json={"input_per_1k": 2, "output_per_1k": 8})
    assert priced.status_code == 201, priced.text
    models = client.get(api("/admin/models")).json()["models"]
    assert models[0]["current_price"]["input_per_1k"] == 2
    assert models[0]["not_listed_reasons"] == ["missing_channel"]
    prices = client.get(api("/admin/models/deepseek-chat/prices")).json()["prices"]
    assert len(prices) == 1


def test_admin_channel_api_never_returns_the_upstream_key(client):
    make_admin(client)
    with client.app.state.db.session() as db:
        db.add(CloudGatewayModel(id="m1", label="M1", kind="chat", max_output_tokens=100))
        db.commit()
    config = replace(client.app.state.config, channel_key=Fernet.generate_key().decode("ascii"))
    with client.app.state.db.session() as db:
        channel = service.create_channel(
            db,
            config,
            model_id="m1",
            base_url="https://upstream.example/v1",
            upstream_model="m1",
            api_key="sk-never-return-this",
            priority=0,
            note="",
        )
        db.commit()
    assert channel["has_api_key"] is True
    assert "sk-never-return-this" not in str(channel)


def test_channel_connectivity_test_uses_the_stored_key_without_returning_it(client):
    make_admin(client)
    with client.app.state.db.session() as db:
        db.add(CloudGatewayModel(id="m2", label="M2", kind="chat", max_output_tokens=100))
        db.commit()
    config = replace(client.app.state.config, channel_key=Fernet.generate_key().decode("ascii"))
    seen = {}
    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx2.Response(200, json={"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    with client.app.state.db.session() as db:
        channel = service.create_channel(
            db, config, model_id="m2", base_url="https://upstream.example/v1",
            upstream_model="m2", api_key="sk-test", priority=0, note="",
        )
        db.commit()
        result = service.test_channel(db, config, channel["id"], transport=httpx2.MockTransport(handler))
    assert result["ok"] is True
    assert result["status"] == 200
    assert seen["auth"] == "Bearer sk-test"
    assert "sk-test" not in str(result)


def test_admin_can_read_orders_and_usage_summary(client):
    make_admin(client)
    signup(client, email="usage@example.com", password=PASSWORD)
    login(client, email="admin@example.com", password=PASSWORD)
    with client.app.state.db.session() as db:
        user = db.scalar(select(CloudUser).where(CloudUser.email == "usage@example.com"))
        db.add(
            CloudGatewayCall(
                user_id=user.id,
                model_id="m1",
                status="settled",
                reserved=10,
                charged=3,
                input_tokens=10,
                output_tokens=5,
            )
        )
        db.commit()

    orders = client.get(api("/admin/orders"))
    assert orders.status_code == 200
    assert orders.json() == {"orders": []}

    usage = client.get(api("/admin/usage"), params={"days": 7})
    assert usage.status_code == 200
    body = usage.json()
    assert body["totals"]["calls"] == 1
    assert body["totals"]["charged"] == 3
    assert body["by_model"][0]["model_id"] == "m1"
