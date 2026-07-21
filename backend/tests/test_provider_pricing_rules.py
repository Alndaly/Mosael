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
