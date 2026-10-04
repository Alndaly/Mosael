"""补算老账的第二步:已经有费用、但明显是按旧规则「只算了估的提示词 token」少算的那批,按现在的规则重算。

用户库里 147ai 的 gpt-image-2 有 15 次成功生图:回包里写着文字输入、参考图输入、图像输出的 token 数,
账上却只按请求侧估的十几个输入 token 记了几十 micros(合计 $0.0027,实际约 $0.18)。第一步补算
(backfill-usage-costs)按「已有费用不动」没碰它们;用户拍板这批也改正。

**判据要窄**,四条都满足才动:
1. 生图 / 生视频 / 生音频,可信度是 `estimated`(当时按价目估的);
2. 计量里的 token 是按提示词估的(`token_estimate`),而且没有输出 token;
3. 回包里服务商报了输出 token —— 当时根本没进账的那一项;
4. 记下的费用**正好等于**旧规则拿这份计量算出来的数(估的 token 当真计价)—— 说明它就是那样算出来的,
   不是用户手改的、不是别的规则算的。

重算用现在的读法和规则(和记账同一处),可信度记 `backfilled`;重跑什么都不变(重算过的计量里已经没有估算)。
"""

from __future__ import annotations

from datetime import datetime

from app.core.db import SessionLocal
from app.db.migrations import _reprice_usage_billed_on_estimated_prompt_tokens
from app.db.models import ProviderUsageEvent
from app.domain.billing.usage import create_pricing_rule
from tests.billing_samples import GPT_IMAGE_CLIENT_WITH_REFERENCES, GPT_IMAGE_TEXT_ONLY, QWEN_IMAGE_REJECTED
from tests.util import fresh_client

WHEN = datetime(2026, 9, 14, 13, 34, 34)


def _event(db, ws: str, key: str, *, sample: dict, cost_micros: int | None, model: str = "gpt-image-2",
           provider: str = "openai-compatible", capability: str = "image", cost_confidence: str = "estimated",
           currency: str = "USD") -> None:
    db.add(ProviderUsageEvent(
        workspace_id=ws, provider=provider, model=model, capability=capability, operation="generation_job",
        status="succeeded", units=dict(sample["units"]), raw_usage=dict(sample["raw"]), cost_micros=cost_micros,
        currency=currency, cost_confidence=cost_confidence, idempotency_key=key, created_at=WHEN,
    ))


def _snapshot() -> dict[str, tuple]:
    with SessionLocal() as db:
        return {e.idempotency_key: (e.cost_micros, e.currency, e.cost_confidence, e.units) for e in db.query(ProviderUsageEvent)}


def test_only_costs_the_old_rule_computed_from_estimated_prompt_tokens_are_repriced() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        for unit, micros in (("million_input_token", 5_000_000), ("million_image_input_token", 8_000_000),
                             ("million_output_token", 30_000_000)):
            create_pricing_rule(db, provider="openai-compatible", capability="image", model="gpt-image-2",
                                billing_unit=unit, unit_amount_micros=micros, currency="USD")
        create_pricing_rule(db, provider="alibaba", capability="image", model="qwen-image",
                            billing_unit="image", unit_amount_micros=250_000, currency="CNY")
        create_pricing_rule(db, provider="openai-compatible", capability="chat", model="gpt-5.5",
                            billing_unit="million_input_token", unit_amount_micros=5_000_000, currency="USD")
        # 旧规则只按估的 14 个输入 token 记了 14 × $5 / 百万 = 70 micros —— 回包里有 196 个输出 token。
        _event(db, ws, "text-only", sample=GPT_IMAGE_TEXT_ONLY, cost_micros=70)
        # 带两张参考图那次:估的 100 个输入 token → 500 micros。
        _event(db, ws, "with-refs", sample=GPT_IMAGE_CLIENT_WITH_REFERENCES, cost_micros=500)
        # 不该动的:
        _event(db, ws, "hand-edited", sample=GPT_IMAGE_TEXT_ONLY, cost_micros=6_000)  # 费用对不上旧规则的算法
        _event(db, ws, "reported", sample=GPT_IMAGE_TEXT_ONLY, cost_micros=70, cost_confidence="reported")
        _event(db, ws, "already-right", cost_micros=5_975, sample={
            "units": {**GPT_IMAGE_TEXT_ONLY["units"], "output_tokens": 196, "total_tokens": 215},
            "raw": GPT_IMAGE_TEXT_ONLY["raw"],
        })
        _event(db, ws, "no-usage-reported", cost_micros=70,
               sample={"units": GPT_IMAGE_TEXT_ONLY["units"], "raw": {"data": [{}], "size": "1024x1024"}})
        _event(db, ws, "per-image", provider="alibaba", model="qwen-image", cost_micros=250_000, currency="CNY",
               sample={"units": {"requests": 1, "input_tokens": 7, "total_tokens": 7, "token_estimate": True, "images": 1},
                       "raw": {"usage": {"image_count": 1}}})
        _event(db, ws, "chat", provider="openai-compatible", model="gpt-5.5", capability="chat", cost_micros=70,
               sample={"units": GPT_IMAGE_TEXT_ONLY["units"], "raw": GPT_IMAGE_TEXT_ONLY["raw"]})
        _event(db, ws, "rejected", provider="alibaba", model="qwen-image", cost_micros=0, currency="CNY",
               cost_confidence="not_billed", sample=QWEN_IMAGE_REJECTED)
        db.commit()
    before = _snapshot()

    _reprice_usage_billed_on_estimated_prompt_tokens()
    after = _snapshot()

    assert after["text-only"][:3] == (5_975, "USD", "backfilled"), "19 × $5 + 196 × $30(每百万)"
    assert after["text-only"][3]["output_tokens"] == 196 and "token_estimate" not in after["text-only"][3]
    assert after["with-refs"][:3] == (62_715, "USD", "backfilled"), "215 × $5 + 1120 × $8 + 1756 × $30"
    for key in ("hand-edited", "reported", "already-right", "no-usage-reported", "per-image", "chat", "rejected"):
        assert after[key] == before[key], f"{key} 不该动"

    _reprice_usage_billed_on_estimated_prompt_tokens()
    assert _snapshot() == after, "重跑什么都不变"


def test_an_empty_library_is_left_alone() -> None:
    fresh_client()
    _reprice_usage_billed_on_estimated_prompt_tokens()
    assert _snapshot() == {}
