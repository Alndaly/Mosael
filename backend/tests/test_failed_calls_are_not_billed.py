"""失败的调用:**服务商没回报用量或扣费,就不计费;回报了,照它记。**

此前失败的调用和成功的一样按请求侧计量套价:一次当场被拒、什么都没产出的 qwen-image 请求,
按「请求两张」记了 ¥0.5。那笔钱从来没被扣过,而付费测试的控费规则正是读这张账累计到上限就停 ——
账上多出来的钱会让它提前停,账上少的钱会让它超支,两头都不行。

请求侧的计量(请求了几张、几秒、什么分辨率)照旧留在账上:「最近失败了多少次、都是什么请求」
本身就是用户想看的,只是它不是扣费的依据。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ProviderPricingRule
from app.domain.billing.usage import record_usage
from tests.billing_samples import QWEN_IMAGE_REJECTED
from tests.util import fresh_client


def _qwen_rule(db, ws: str) -> None:
    db.add(
        ProviderPricingRule(
            workspace_id=ws,
            provider="alibaba",
            capability="image",
            model="qwen-image",
            billing_unit="image",
            unit_amount_micros=250_000,
            currency="CNY",
        )
    )
    db.flush()


def test_a_rejected_request_with_nothing_reported_costs_nothing() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        _qwen_rule(db, ws)
        event = record_usage(
            db,
            workspace_id=ws,
            provider="alibaba",
            model="qwen-image",
            capability="image",
            operation="generation_job",
            idempotency_key="gen-rejected:failed",
            status="failed",
            units=QWEN_IMAGE_REJECTED["units"],
            raw_usage=QWEN_IMAGE_REJECTED["raw"],
        )
        db.commit()

    assert event.cost_micros == 0, "当场被拒、服务商什么都没回 —— 没扣过的钱不该进账"
    assert event.cost_confidence == "not_billed"
    # 币种跟着这个模型的价走:¥0 和这家其余的人民币账放在一起,不另起一个 $0 的币种。
    assert event.currency == "CNY"
    assert event.units["images"] == 2, "请求侧的计量照旧留着,只是不按它计费"


def test_a_failure_the_provider_reported_usage_for_is_billed_as_reported() -> None:
    """有的平台失败也扣:回包里报了用量,就照它算。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        _qwen_rule(db, ws)
        event = record_usage(
            db,
            workspace_id=ws,
            provider="alibaba",
            model="qwen-image",
            capability="image",
            operation="generation_job",
            idempotency_key="gen-partial:failed",
            status="failed",
            units={"requests": 1, "images": 1},
            raw_usage={"usage": {"image_count": 1}},
        )
        db.commit()

    assert (event.cost_micros, event.currency, event.cost_confidence) == (250_000, "CNY", "estimated")


def test_a_failure_with_a_reported_charge_keeps_that_charge() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    with SessionLocal() as db:
        event = record_usage(
            db,
            workspace_id=ws,
            provider="evolink",
            model="seedance-2.5-image-to-video",
            capability="video",
            operation="generation_job",
            idempotency_key="gen-charged:failed",
            status="failed",
            units={"requests": 1, "videos": 1},
            cost_micros=120_000,
            currency="USD",
            cost_confidence="reported",
        )
        db.commit()

    assert (event.cost_micros, event.currency, event.cost_confidence) == (120_000, "USD", "reported")
