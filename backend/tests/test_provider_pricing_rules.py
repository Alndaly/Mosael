from __future__ import annotations

from app.core.db import SessionLocal
from app.domain.usage import record_usage
from tests.util import fresh_client


def test_provider_pricing_rules_crud_and_metering() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    profile = client.post(
        "/api/settings/providers",
        json={"name": "百炼 qwen", "vendor": "alibaba", "config": {"api_key": "dashscope-key"}},
    ).json()

    created = client.post(
        "/api/settings/provider-pricing-rules",
        json={
            "workspace_id": workspace_id,
            "provider_profile_id": profile["id"],
            "capability": "image",
            "model": "qwen-image",
            "billing_unit": "image",
            "unit_amount_micros": 25_000,
            "currency": "CNY",
            "notes": "manual test price",
        },
    )
    assert created.status_code == 200
    rule = created.json()
    assert rule["provider"] == "alibaba"
    assert rule["currency"] == "CNY"

    listed = client.get(f"/api/settings/provider-pricing-rules?workspace_id={workspace_id}").json()
    assert [item["id"] for item in listed] == [rule["id"]]

    patched = client.patch(
        f"/api/settings/provider-pricing-rules/{rule['id']}",
        json={"unit_amount_micros": 30_000, "notes": "updated"},
    ).json()
    assert patched["unit_amount_micros"] == 30_000
    assert patched["notes"] == "updated"

    with SessionLocal() as db:
        event = record_usage(
            db,
            workspace_id=workspace_id,
            provider_profile_id=profile["id"],
            provider="alibaba",
            model="qwen-image",
            capability="image",
            operation="generation_job",
            idempotency_key="pricing-crud-event",
            units={"images": 2},
        )
        db.commit()

    assert event.cost_micros == 60_000
    assert event.currency == "CNY"
    assert event.cost_confidence == "estimated"

    assert client.delete(f"/api/settings/provider-pricing-rules/{rule['id']}").status_code == 204
    assert client.get(f"/api/settings/provider-pricing-rules?workspace_id={workspace_id}").json() == []


def test_计价规则的读也有门_别人的工作区读不到() -> None:
    """写入一直要部署管理员,读却对任何登录用户开放 —— A 工作区的成员因此能看到 B 谈下来的单价。

    一张表两套判据时,漏的那一半不会报错:界面照样好用,只是多给了别人一眼。
    """
    from tests.util import second_client

    client = fresh_client()
    theirs = client.post("/api/workspaces", json={"name": "别人的"}).json()["id"]
    created = client.post("/api/settings/provider-pricing-rules", json={
        "workspace_id": theirs, "provider": "openai", "capability": "image", "model": "m",
        "billing_unit": "image", "unit_amount_micros": 25_000, "currency": "CNY",
    })
    assert created.status_code == 200, created.text
    assert client.get(f"/api/settings/provider-pricing-rules?workspace_id={theirs}").status_code == 200

    outsider = second_client("outsider")
    assert outsider.get(f"/api/settings/provider-pricing-rules?workspace_id={theirs}").status_code == 404, \
        "不是成员就不该读到"
    assert outsider.get("/api/settings/provider-pricing-rules").status_code == 403, \
        "不带工作区 = 全库视图,只给部署管理员"
