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


def test_record_usage_sums_input_and_output_token_pricing_rules() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        db.add(
            ProviderPricingRule(
                workspace_id=ws,
                provider="openai-compatible",
                capability="chat",
                model="deepseek-v4-pro",
                billing_unit="million_input_token",
                unit_amount_micros=435_000,
                currency="USD",
            )
        )
        db.add(
            ProviderPricingRule(
                workspace_id=ws,
                provider="openai-compatible",
                capability="chat",
                model="deepseek-v4-pro",
                billing_unit="million_output_token",
                unit_amount_micros=870_000,
                currency="USD",
            )
        )
        db.flush()
        event = record_usage(
            db,
            workspace_id=ws,
            provider="openai-compatible",
            model="deepseek-v4-pro",
            capability="chat",
            operation="agent_chat",
            idempotency_key="deepseek-token-event",
            units={"input_tokens": 1_000_000, "output_tokens": 2_000_000},
        )
        db.commit()

    assert event.cost_micros == 2_175_000
    assert event.currency == "USD"
    assert event.cost_confidence == "estimated"
    assert event.pricing_rule_id is None


def test_summarize_usage_estimates_token_count_from_character_units() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        db.add(
            ProviderUsageEvent(
                workspace_id=ws,
                provider="openai-compatible",
                model="deepseek-v4-pro",
                capability="chat",
                operation="agent_chat",
                idempotency_key="character-token-estimate",
                units={"input_characters": 4, "output_characters": 12},
            )
        )
        db.commit()

    with SessionLocal() as db:
        summary = summarize_usage(db, workspace_id=ws)
    assert summary.token_count == 16
    assert summary.token_daily[-1]["input_tokens"] == 4
    assert summary.token_daily[-1]["output_tokens"] == 12


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
                units={"images": 1, "input_tokens": 100, "output_tokens": 25},
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
                units={"video_seconds": 5, "total_tokens": 80},
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
    assert summary["usage_token_count"] == 205
    assert summary["usage_daily"][-1]["events"] == 2
    assert summary["usage_token_daily"][-1] == {
        "date": summary["usage_daily"][-1]["date"],
        "input_tokens": 100,
        "output_tokens": 25,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 205,
    }
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


def test_缓存读写单列并算出命中率() -> None:
    """缓存这两桶此前落进图表的「其他」里 —— "省下多少"是长对话最大的变量,却看不见。

    命中率的分母是**提示词总量**(input + cacheRead + cacheWrite,三者不相交),
    不是 total_tokens:把补全 token 算进去会让这个比例随回答长短漂移。
    """
    from app.domain.usage import _token_usage

    split = _token_usage({"input_token": 300, "output_token": 100, "cache_read_token": 700, "cache_write_token": 0})
    assert split == {
        "input_tokens": 300,
        "output_tokens": 100,
        "cache_read_tokens": 700,
        "cache_write_tokens": 0,
        "total_tokens": 1100,
    }

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        record_usage(
            db,
            workspace_id=ws,
            provider="openai-compatible",
            model="m",
            capability="chat",
            operation="chat",
            source_type="agent",
            source_id="s1",
            idempotency_key="cache-probe-1",
            units={"input_token": 300, "output_token": 100, "cache_read_token": 700},
            raw_usage={},
        )
        db.commit()
    summary = client.get(f"/api/workspaces/{ws}/summary").json()
    assert summary["usage_cache_read_tokens"] == 700
    assert summary["usage_cache_write_tokens"] == 0
    # 700 / (300 + 700 + 0) = 0.7
    assert summary["usage_cache_hit_ratio"] == 0.7
    assert summary["usage_token_daily"][-1]["cache_read_tokens"] == 700
