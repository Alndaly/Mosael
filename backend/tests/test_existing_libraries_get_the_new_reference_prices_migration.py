"""已有的库补上这一版新增的内置参考价。

内置价目表(domain/billing/price_reference)进库只有一条路:管理员在成本规则里点「预填」。新装的库也一样 ——
所以这一版新加的价(分辨率分档、GPT Image 的输入价、147ai 的 gpt-image-2-client、Evolink、海螺 H3)在老库里
不点就不会有,而下一步的补算老账正要用它们。

迁移照预填的规则走(只补不改、不混币种、只补模型行上真会用到的能力),但**只补这一版新增的那些型号**:
用户一直没给 DeepSeek 点预填,那是他的选择,升级不替他补。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_existing_libraries_get_the_new_reference_prices
from app.db.models import ProviderPricingRule
from app.domain.billing.usage import create_pricing_rule
from tests.util import add_provider, fresh_client


def _rules() -> set[tuple[str, str, str, str, int]]:
    with SessionLocal() as db:
        return {
            (rule.model, rule.billing_unit, rule.resolution, rule.currency, rule.unit_amount_micros)
            for rule in db.query(ProviderPricingRule)
        }


def test_existing_libraries_get_this_versions_reference_prices_once() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        bailian = add_provider(db, name="百炼", vendor="alibaba", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                               api_key="k", model="wan2.7-t2v", capability_ids=["video"], make_default=False)
        minimax = add_provider(db, name="MiniMax", vendor="minimax", base_url="https://api.minimaxi.com/v1",
                               api_key="k", model="MiniMax-H3", capability_ids=["video"], make_default=False)
        relay = add_provider(db, name="147ai", vendor="openai-compatible", base_url="https://147ai.com/v1",
                             api_key="k", model="gpt-image-2-client", capability_ids=["image"], make_default=False)
        add_provider(db, name="DeepSeek", vendor="deepseek", base_url="https://api.deepseek.com",
                     api_key="k", model="deepseek-v4-pro", capability_ids=["chat"], make_default=False)
        from app.domain.providers import models as provider_models

        provider_models.upsert(db, relay, "gpt-image-2", capability_ids=["image"])
        # 老库里已有的:万相那条只能记 720P 一档的价;147ai 的 gpt-image-2 用户自己配过输入 / 输出两条。
        create_pricing_rule(db, provider_profile_id=bailian.id, provider="alibaba", capability="video", model="wan2.7-t2v",
                            billing_unit="video_second", unit_amount_micros=600_000, currency="CNY", source="reference")
        for unit, micros in (("million_input_token", 5_000_000), ("million_output_token", 30_000_000)):
            create_pricing_rule(db, workspace_id=ws, provider_profile_id=relay.id, provider="openai-compatible",
                                capability="image", model="gpt-image-2", billing_unit=unit, unit_amount_micros=micros,
                                currency="USD", source="official-reference")
        db.commit()
        minimax_id = minimax.id
    before = _rules()

    _migrate_existing_libraries_get_the_new_reference_prices()
    after = _rules()
    assert after - before == {
        ("wan2.7-t2v", "video_second", "1080p", "CNY", 1_000_000),
        ("MiniMax-H3", "video_second", "", "CNY", 500_000),
        ("MiniMax-H3", "video_second", "2k", "CNY", 800_000),
        ("gpt-image-2-client", "million_input_token", "", "USD", 5_000_000),
        ("gpt-image-2-client", "million_image_input_token", "", "USD", 8_000_000),
        ("gpt-image-2-client", "million_output_token", "", "USD", 30_000_000),
        ("gpt-image-2", "million_image_input_token", "", "USD", 8_000_000),
    }
    assert before <= after, "已有规则一条都不动"
    assert not any(model == "deepseek-v4-pro" for model, *_ in after), "不是这一版新增的型号,升级不替用户补"
    with SessionLocal() as db:
        h3 = db.query(ProviderPricingRule).filter_by(provider_profile_id=minimax_id, resolution="2k").one()
        assert h3.source == "reference" and "2K" in h3.notes

    _migrate_existing_libraries_get_the_new_reference_prices()
    assert _rules() == after, "重跑什么都不变"


def test_an_empty_library_is_left_alone() -> None:
    fresh_client()
    _migrate_existing_libraries_get_the_new_reference_prices()
    assert _rules() == set()
