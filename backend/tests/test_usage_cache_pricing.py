from __future__ import annotations

from app.domain.usage import PRICING_BILLING_UNITS, _quantity_for_unit

"""缓存 token 的计价。

这条以前是**静默少算**:适配器上报了 cache_read_tokens,但计价单位表里没有对应项,
`_quantity_for_unit` 匹配不到任何规则就直接跳过 —— 没有报错、没有告警,只是费用偏低。
长上下文的重复对话里缓存读往往是输入量的数倍,差额不小。

关键前提(决定这些桶不能合并):供应商的 `prompt_tokens` 是**含缓存**的总量,而 pi 在上报前
已经减掉了 —— `input = max(0, prompt_tokens - cacheRead - cacheWrite)`,`totalTokens` 也是四者
相加。所以 input / output / cacheRead / cacheWrite **互不相交**,各自计价才是对的:
并进 input 会按输入价收缓存读(约十倍高),不计则少算。
"""


def test_cache_units_are_priceable() -> None:
    for unit in ("cache_read_token", "cache_write_token",
                 "million_cache_read_token", "million_cache_write_token"):
        assert unit in PRICING_BILLING_UNITS, f"{unit} 不可计价 → 该项用量会被静默丢弃"


def test_each_bucket_resolves_independently() -> None:
    """四个桶各取各的,不串味。"""
    units = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_read_tokens": 8000,
        "cache_write_tokens": 500,
    }
    assert _quantity_for_unit(units, "input_token") == 1000
    assert _quantity_for_unit(units, "output_token") == 200
    assert _quantity_for_unit(units, "cache_read_token") == 8000
    assert _quantity_for_unit(units, "cache_write_token") == 500


def test_cache_read_never_leaks_into_input() -> None:
    """只有缓存读时,input 必须取不到值 —— 否则就是按输入价收缓存读,约十倍高估。"""
    assert _quantity_for_unit({"cache_read_tokens": 8000}, "input_token") is None


def test_million_prefix_scales_cache_units() -> None:
    units = {"cache_read_tokens": 8000, "cache_write_tokens": 250_000}
    assert _quantity_for_unit(units, "million_cache_read_token") == 0.008
    assert _quantity_for_unit(units, "million_cache_write_token") == 0.25


def test_prompt_tokens_still_works_as_a_fallback() -> None:
    """不拆分的来源仍按 prompt_tokens 计入 input,老数据与老适配器不受影响。"""
    assert _quantity_for_unit({"prompt_tokens": 1500}, "input_token") == 1500


def test_cache_read_actually_produces_cost_end_to_end() -> None:
    """整条链路:配了缓存规则 → 记账里真的多出这笔钱。

    上面几条测的是单位解析,这条测的是**钱**:以前缓存读那一项在这里悄无声息地变成 0。
    """
    from app.core.db import SessionLocal
    from app.domain.usage import create_pricing_rule, record_usage
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        for unit, micros in (
            ("million_input_token", 3_000_000),      # $3 / 1M
            ("million_output_token", 15_000_000),    # $15 / 1M
            ("million_cache_read_token", 300_000),   # $0.30 / 1M —— 约为输入价一成
        ):
            create_pricing_rule(
                db, workspace_id=ws, provider="p", capability="chat", model="m",
                billing_unit=unit, unit_amount_micros=micros,
            )
        event = record_usage(
            db, workspace_id=ws, provider="p", capability="chat", model="m",
            units={"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_tokens": 5_000_000},
            operation="chat.turn",
            idempotency_key="cache-pricing-test",
        )

    # 3.00(输入) + 1.50(输出) + 1.50(缓存读) = 6.00
    assert event.cost_micros == 6_000_000, (
        f"合计应为 $6.00,实际 ${(event.cost_micros or 0) / 1e6:.2f}"
        " —— 少 $1.50 说明缓存读那一项又被丢了"
    )
