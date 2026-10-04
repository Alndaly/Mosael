"""老库补上 Evolink GPT Image 的内置参考价。

「补新增参考价」那一步(migrate-existing-libraries-get-the-new-reference-prices)已经在 main 上,身体不能再改,
它列的型号里也没有 gpt-image-2-beta;这一步只补 Evolink 的四个 GPT Image 型号,规则和点「预填」一样:只补
模型行上配了的、只补不改。连接上还没启用这几个型号的,启用之后点一次「预填」就有。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_existing_libraries_get_the_evolink_gpt_image_prices
from app.db.models import ProviderPricingRule
from app.domain.billing.usage import create_pricing_rule
from tests.util import add_provider, fresh_client


def _rules() -> set[tuple[str, str, int]]:
    with SessionLocal() as db:
        return {(rule.model, rule.billing_unit, rule.unit_amount_micros) for rule in db.query(ProviderPricingRule)}


def test_evolink_gpt_image_prices_reach_existing_libraries_once() -> None:
    fresh_client()
    with SessionLocal() as db:
        evolink = add_provider(db, name="Evolink", vendor="evolink", base_url="https://api.evolink.ai/v1", api_key="k",
                               model="gpt-image-2", capability_ids=["image"], make_default=False)
        from app.domain.providers import models as provider_models

        provider_models.upsert(db, evolink, "gpt-image-2-beta", capability_ids=["image"])
        provider_models.upsert(db, evolink, "seedance-2.5-image-to-video", capability_ids=["video"])
        # 用户自己配过一条 gpt-image-2 的输出价:不动它,只补缺的那两格。
        create_pricing_rule(db, provider_profile_id=evolink.id, provider="evolink", capability="image", model="gpt-image-2",
                            billing_unit="million_output_token", unit_amount_micros=25_000_000, currency="USD")
        db.commit()
    before = _rules()

    _migrate_existing_libraries_get_the_evolink_gpt_image_prices()
    after = _rules()
    assert after - before == {
        ("gpt-image-2", "million_image_input_token", 7_200_000),
        ("gpt-image-2", "million_input_token", 4_500_000),
        ("gpt-image-2-beta", "image", 15_000),
    }, "只补 GPT Image 那几个型号,Seedance 不在这一步的范围里"
    assert ("gpt-image-2", "million_output_token", 25_000_000) in after, "用户配的价一个字都不动"

    _migrate_existing_libraries_get_the_evolink_gpt_image_prices()
    assert _rules() == after, "重跑什么都不变"


def test_an_empty_library_is_left_alone() -> None:
    fresh_client()
    _migrate_existing_libraries_get_the_evolink_gpt_image_prices()
    assert _rules() == set()
