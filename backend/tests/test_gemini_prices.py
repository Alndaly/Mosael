"""Gemini 对话的官方价:查得到、预填得上、按 pi 报的 token 算得对,老库升级时补上。

数字逐条对过 https://ai.google.dev/gemini-api/docs/pricing(2026-10,Standard 档)。这里不复读每一个数,钉的是
**容易写错而且错了没人发现**的那几处:单位是每百万 token、缓存命中单列、超 200K 与 2027 年新价写进了备注、
音频输入价没混进来、只有 Gemini 对话模型有价、算一轮智能体的账用的是 pi 报回来的那三个数。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.ai.gemini_models import is_chat_model
from app.core.db import SessionLocal
from app.db.migrations import _migrate_existing_libraries_get_the_gemini_chat_prices, migration_plan
from app.db.models import ProviderPricingRule
from app.domain.billing import price_reference
from app.domain.billing.pricing_prefill import prefill_profile_pricing
from app.domain.billing.usage import record_usage
from app.domain.providers import models as provider_models
from tests.util import add_provider, fresh_client

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"


def _prices(model: str) -> dict[str, str]:
    region = price_reference.region_for("google", GEMINI_BASE)
    return {entry.billing_unit: entry.amount for entry in price_reference.lookup("google", model, region=region)}


def test_每个_gemini_对话模型三格价_每百万_token() -> None:
    assert _prices("gemini-2.5-pro") == {
        "million_input_token": "1.25",
        "million_output_token": "10",
        "million_cache_read_token": "0.125",
    }
    assert _prices("gemini-2.5-flash") == {
        "million_input_token": "0.3",
        "million_output_token": "2.5",
        "million_cache_read_token": "0.03",
    }
    assert _prices("gemini-3-flash-preview") == {
        "million_input_token": "0.5",
        "million_output_token": "3",
        "million_cache_read_token": "0.05",
    }
    assert _prices("gemini-3.1-pro-preview") == {
        "million_input_token": "2",
        "million_output_token": "12",
        "million_cache_read_token": "0.2",
    }
    assert _prices("gemini-3.8-flash")["million_input_token"] == "0.75"
    assert _prices("gemini-flash-latest") == {}, "别名背后的型号会变,不收"


def test_每一条都出自官方价目页_而且只给对话模型() -> None:
    gemini = [entry for entry in price_reference.LIST_PRICES if entry.vendor == "google" and entry.capability == "chat"]
    assert {entry.model for entry in gemini} == {
        "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite", "gemini-3.1-pro-preview", "gemini-3.1-pro-preview-customtools",
        "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
    }
    for entry in gemini:
        assert entry.source == SOURCE and entry.checked == "2026-10" and entry.currency == "USD"
        assert is_chat_model(entry.model), f"{entry.model} 不是目录会列出来的对话模型,价永远用不上"


def test_分档的价写在备注里() -> None:
    region = price_reference.region_for("google", GEMINI_BASE)
    [pro_in] = [e for e in price_reference.lookup("google", "gemini-2.5-pro", region=region) if e.billing_unit == "million_input_token"]
    assert "$2.50" in pro_in.remark[1] and "200K" in pro_in.remark[1]
    [pro31] = [e for e in price_reference.lookup("google", "gemini-3.1-pro-preview", region=region) if e.billing_unit == "million_output_token"]
    assert "$18" in pro31.remark[1]
    [flash38] = [e for e in price_reference.lookup("google", "gemini-3.8-flash", region=region) if e.billing_unit == "million_input_token"]
    assert "2027-01-01" in flash38.remark[1] and "$1.50" in flash38.remark[1]
    [flash25] = [e for e in price_reference.lookup("google", "gemini-2.5-flash", region=region) if e.billing_unit == "million_input_token"]
    assert "audio input is $1.00" in flash25.remark[1]


def test_改了服务地址的_google_连接按中转算() -> None:
    assert not price_reference.is_relay("google", GEMINI_BASE)
    assert price_reference.is_relay("google", "https://my-gemini-relay.example/v1beta")
    # 中转上同名的 Gemini 型号只有 Google 一家在卖,借它的价。
    assert {entry.vendor for entry in price_reference.lookup_for_relay("gemini-2.5-flash")} == {"google"}


def _google_connection(db, *models_and_caps: tuple[str, list[str] | None]):
    first, caps = models_and_caps[0]
    profile = add_provider(db, name="Gemini", vendor="google", base_url=GEMINI_BASE, api_key="k",
                           auth_type="api_key", model=first, capability_ids=caps, make_default=False)
    for model_id, capability_ids in models_and_caps[1:]:
        provider_models.upsert(db, profile, model_id, capability_ids=capability_ids)
    return profile


def _rules(db, profile_id: str) -> set[tuple[str, str, int]]:
    return {
        (rule.model, rule.billing_unit, rule.unit_amount_micros)
        for rule in db.scalars(select(ProviderPricingRule).where(ProviderPricingRule.provider_profile_id == profile_id))
    }


def test_预填之后一轮智能体按_pi_报的三个数算钱() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = _google_connection(db, ("gemini-2.5-flash", None), ("veo", ["video"]))
        outcome = prefill_profile_pricing(db, profile, base_url=GEMINI_BASE, catalog=[])
        assert outcome.created_from_reference == 3, "只有 Gemini 那一行有对话价;Veo 那行不该冒出对话规则"
        assert _rules(db, profile.id) == {
            ("gemini-2.5-flash", "million_input_token", 300_000),
            ("gemini-2.5-flash", "million_output_token", 2_500_000),
            ("gemini-2.5-flash", "million_cache_read_token", 30_000),
        }
        # sidecar 的 collectUsage 报回来的形状:input 已扣掉缓存命中,思考计在 output 里。
        event = record_usage(
            db,
            user_id=None,
            workspace_id=workspace,
            provider_profile_id=profile.id,
            provider="google",
            model="gemini-2.5-flash",
            capability="chat",
            operation="agent_turn",
            idempotency_key="gemini-turn-1",
            units={"input_tokens": 1_000, "output_tokens": 200, "cache_read_tokens": 4_000, "requests": 2},
        )
        db.commit()
        expected = Decimal(1_000) * Decimal("0.3") + Decimal(200) * Decimal("2.5") + Decimal(4_000) * Decimal("0.03")
        assert event.cost_confidence == "estimated"
        assert (event.cost_micros, event.currency) == (int(expected), "USD")


def test_老库升级_有_gemini_对话模型行的_google_连接补上价() -> None:
    fresh_client()
    assert "migrate-existing-libraries-get-the-gemini-chat-prices" in {step.name for step in migration_plan().steps}
    with SessionLocal() as db:
        # 升级前就有人给素材分析的原生视频手动加过一行 Gemini、标成对话。
        analysis = _google_connection(db, ("gemini-2.5-pro", ["chat"]), ("veo", ["video"]))
        veo_only = _google_connection(db, ("veo", ["video"]))
        other = add_provider(db, name="DeepSeek", vendor="deepseek", base_url="https://api.deepseek.com",
                             api_key="k", model="deepseek-v4-pro", capability_ids=["chat"], make_default=False)
        db.commit()
        ids = (analysis.id, veo_only.id, other.id)

    _migrate_existing_libraries_get_the_gemini_chat_prices()
    with SessionLocal() as db:
        assert _rules(db, ids[0]) == {
            ("gemini-2.5-pro", "million_input_token", 1_250_000),
            ("gemini-2.5-pro", "million_output_token", 10_000_000),
            ("gemini-2.5-pro", "million_cache_read_token", 125_000),
        }
        assert _rules(db, ids[1]) == set()
        assert _rules(db, ids[2]) == set(), "别家没点过预填,升级不替它补"
        before = _rules(db, ids[0])

    _migrate_existing_libraries_get_the_gemini_chat_prices()
    with SessionLocal() as db:
        assert _rules(db, ids[0]) == before, "重跑什么都不变"
