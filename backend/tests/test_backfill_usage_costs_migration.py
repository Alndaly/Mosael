"""补算老账:费用为空、但现在按价目或服务商回报算得出来的历史用量,补上费用,可信度 `backfilled`。

用户过去两个多月的生图生视频,账上记了 ¥18.8,按服务商回报的用量乘价目实际约 ¥54.7:方舟 Seedance 的成片 token
数在回包里、当时没读进计量;147ai 的 gpt-image-2-client 当时没价;Evolink 回包里写着实扣;还有一张 seedream 是先
用了、后来才配的价。这些都在库里存着 —— 回包(raw_usage)和请求侧计量(units)都在,只差按现在的读法算一遍。

**保守**:这个迁移会在用户下次启动时直接作用在他的库上,所以
- 只补生图、生视频、生音频;对话不补(订阅计划按目录价算的是名义价,不是扣费);
- 已经有费用的一律不动(包括当时只按输入估了一点钱的 gpt-image-2 —— 改它要用户拍板);
- 唯一的例外是「失败、当时按请求侧计量估了价、服务商什么都没回」的那几条(当场被拒的请求):按现在的规则改成
  不计费的 0;
- 费用为空的失败调用不补:当场被拒的和「我们没等到、远端照样生成扣了费」的(早年 300 秒超时放弃的 Seedance)
  在库里长得一样,分不清就不猜;
- 算不出来的照旧留空;
- 重跑什么都不变。
"""

from __future__ import annotations

from datetime import datetime

from app.core.db import SessionLocal
from app.db.migrations import _backfill_usage_costs
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import create_pricing_rule
from tests.billing_samples import (
    EVOLINK_SEEDANCE_MINI,
    GPT_IMAGE_CLIENT_WITH_REFERENCES,
    GPT_IMAGE_TEXT_ONLY,
    QWEN_IMAGE_REJECTED,
    SEEDANCE_480P_WITH_AUDIO,
)
from tests.util import fresh_client

WHEN = datetime(2026, 9, 23, 14, 51, 44)


def _event(db, ws: str, key: str, *, provider: str, model: str, capability: str, sample: dict, status: str = "succeeded",
           cost_micros: int | None = None, currency: str = "USD", cost_confidence: str = "unknown") -> None:
    db.add(ProviderUsageEvent(
        workspace_id=ws, provider=provider, model=model, capability=capability, operation="generation_job",
        source_type="generation_job", source_id=key, status=status, units=dict(sample["units"]),
        raw_usage=dict(sample["raw"]), cost_micros=cost_micros, currency=currency, cost_confidence=cost_confidence,
        idempotency_key=key, created_at=WHEN,
    ))


def _snapshot() -> dict[str, tuple]:
    with SessionLocal() as db:
        return {
            event.idempotency_key: (event.cost_micros, event.currency, event.cost_confidence, event.pricing_rule_id, event.units)
            for event in db.query(ProviderUsageEvent)
        }


def test_backfill_prices_what_can_now_be_priced_and_nothing_else() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        create_pricing_rule(db, provider="bytedance", capability="video", model="doubao-seedance-2-0-260128",
                            billing_unit="million_output_token", unit_amount_micros=46_000_000, currency="CNY")
        for model in ("gpt-image-2-client", "gpt-image-2"):
            for unit, micros in (("million_input_token", 5_000_000), ("million_image_input_token", 8_000_000),
                                 ("million_output_token", 30_000_000)):
                create_pricing_rule(db, provider="openai-compatible", capability="image", model=model,
                                    billing_unit=unit, unit_amount_micros=micros, currency="USD")
        qwen = create_pricing_rule(db, provider="alibaba", capability="image", model="qwen-image",
                                   billing_unit="image", unit_amount_micros=250_000, currency="CNY")
        # 补得出来的
        _event(db, ws, "seedance", provider="bytedance", model="doubao-seedance-2-0-260128", capability="video",
               sample=SEEDANCE_480P_WITH_AUDIO)
        _event(db, ws, "gpt-client", provider="openai-compatible", model="gpt-image-2-client", capability="image",
               sample=GPT_IMAGE_CLIENT_WITH_REFERENCES)
        _event(db, ws, "evolink", provider="evolink", model="seedance-2.0-mini-image-to-video", capability="video",
               sample=EVOLINK_SEEDANCE_MINI)
        _event(db, ws, "late-rule", provider="alibaba", model="qwen-image", capability="image",
               sample={"units": {"requests": 1, "images": 1}, "raw": {"usage": {"image_count": 1}}})
        # 当场被拒、当时却按两张图估了 ¥0.5 的失败
        _event(db, ws, "rejected", provider="alibaba", model="qwen-image", capability="image", status="failed",
               sample=QWEN_IMAGE_REJECTED, cost_micros=500_000, currency="CNY", cost_confidence="estimated")
        db.flush()
        db.query(ProviderUsageEvent).filter_by(idempotency_key="rejected").update({"pricing_rule_id": qwen.id})
        # 不该动的
        _event(db, ws, "partial", provider="openai-compatible", model="gpt-image-2", capability="image",
               sample=GPT_IMAGE_TEXT_ONLY, cost_micros=70, cost_confidence="estimated")
        _event(db, ws, "timed-out", provider="bytedance", model="doubao-seedance-2-0-260128", capability="video",
               status="failed", sample={"units": {"requests": 1, "videos": 1, "video_seconds": 5.0}, "raw": {}})
        _event(db, ws, "no-rule", provider="alibaba", model="wan2.7-t2v", capability="video",
               sample={"units": {"videos": 1, "video_seconds": 5.0, "resolution": "1080P"}, "raw": {}})
        create_pricing_rule(db, provider="kimi-coding", capability="chat", model="k3",
                            billing_unit="million_input_token", unit_amount_micros=3_000_000, currency="USD", source="catalog")
        _event(db, ws, "subscription-chat", provider="kimi-coding", model="k3", capability="chat",
               sample={"units": {"input_tokens": 12_300, "output_tokens": 1_500}, "raw": {"input": 12_300, "output": 1_500}})
        _event(db, ws, "failed-chat", provider="kimi-coding", model="k3", capability="chat", status="failed",
               sample={"units": {"input_tokens": 3}, "raw": {}}, cost_micros=9, cost_confidence="estimated")
        db.commit()
    before = _snapshot()

    _backfill_usage_costs()
    after = _snapshot()

    seedance = after["seedance"]
    assert seedance[:3] == (5_101_492, "CNY", "backfilled"), "110,902 个成片 token × 46 元 / 百万"
    assert seedance[4]["output_tokens"] == 110_902 and "token_estimate" not in seedance[4], "计量照现在的读法补齐"
    assert after["gpt-client"][:3] == (62_715, "USD", "backfilled")
    assert after["gpt-client"][4]["image_input_tokens"] == 1120
    assert after["evolink"][:3] == (198_529, "USD", "backfilled"), "回包里的实扣(13.5 积分 ÷ 68)"
    assert after["late-rule"][:3] == (250_000, "CNY", "backfilled"), "先用了、后来才配的价"
    assert after["rejected"][:4] == (0, "CNY", "not_billed", None)
    for key in ("partial", "timed-out", "no-rule", "subscription-chat", "failed-chat"):
        assert after[key] == before[key], f"{key} 不该动"

    _backfill_usage_costs()
    assert _snapshot() == after, "重跑什么都不变"


def test_an_empty_library_is_left_alone() -> None:
    fresh_client()
    _backfill_usage_costs()
    assert _snapshot() == {}
