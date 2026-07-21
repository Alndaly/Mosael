from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ProviderPricingRule, ProviderUsageEvent
from app.domain.usage import record_usage, summarize_usage
from tests.util import fresh_client


def test_record_usage_estimates_cost_from_pricing_rule() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        db.add(
            ProviderPricingRule(
                workspace_id=ws,
                provider="alibaba",
                capability="image",
                model="qwen-image",
                billing_unit="image",
                unit_amount_micros=25_000,
                currency="CNY",
            )
        )
        db.flush()
        event = record_usage(
            db,
            workspace_id=ws,
            provider="alibaba",
            model="qwen-image",
            capability="image",
            operation="generation_job",
            source_type="generation_job",
            source_id="gen-1",
            idempotency_key="gen-1:succeeded",
            units={"images": 2},
        )
        db.commit()

    assert event.cost_micros == 50_000
    assert event.currency == "CNY"
    assert event.cost_confidence == "estimated"


def test_workspace_summary_includes_usage_rollup() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        db.add(
            ProviderUsageEvent(
                workspace_id=ws,
                provider="openai-compatible",
                model="gpt-image-2",
                capability="image",
                operation="generation_job",
                source_type="generation_job",
                source_id="gen-2",
                idempotency_key="gen-2:succeeded",
                duration_seconds=4.2,
                units={"images": 1},
                cost_micros=120_000,
                currency="USD",
                cost_confidence="estimated",
            )
        )
        db.add(
            ProviderUsageEvent(
                workspace_id=ws,
                provider="bytedance",
                model="doubao-seedance-2-0-260128",
                capability="video",
                operation="generation_job",
                source_type="generation_job",
                source_id="gen-3",
                idempotency_key="gen-3:succeeded",
                units={"video_seconds": 5},
                cost_micros=None,
                cost_confidence="unknown",
            )
        )
        db.commit()

    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    assert summary["usage_cost_micros"] == 120_000
    assert summary["usage_event_count"] == 2
    assert summary["usage_unknown_cost_events"] == 1
    assert summary["usage_duration_seconds"] == 4.2
    assert summary["usage_daily"][-1]["events"] == 2
    assert summary["usage_by_capability"] == {"image": 120_000, "video": 0}
    assert summary["usage_by_provider"] == {"bytedance": 0, "openai-compatible": 120_000}


def test_summarize_usage_scopes_to_workspace() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "W2"}).json()["id"]

    with SessionLocal() as db:
        db.add(
            ProviderUsageEvent(
                workspace_id=other,
                provider="alibaba",
                model="qwen-image",
                capability="image",
                operation="generation_job",
                idempotency_key="foreign",
                cost_micros=999_000,
            )
        )
        db.commit()
        summary = summarize_usage(db, workspace_id=ws)

    assert summary.total_cost_micros == 0
    assert summary.event_count == 0
