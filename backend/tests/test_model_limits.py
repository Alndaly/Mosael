"""内置的模型上限表:形状、优先级、以及「宁可报小」那条。

这张表是**手写的查证结果**(见 app/domain/model_limits 模块头),没有任何上游会纠正它 ——
写错一个数,用户要么白白少掉九成窗口,要么发出一个会被服务端拒的 max_tokens,而两种都不会
在测试里自己暴露出来。所以这里盯的是那几条**写表时容易违反的约定**,而不是逐条复读数字。
"""

from __future__ import annotations

import pytest

from app.domain import model_limits
from app.domain.model_limits import (
    FALLBACK_CONTEXT_WINDOW,
    KNOWN_LIMITS,
    OUTPUT_BUDGET_CAP,
    known_limits,
)

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True


def test_prefixes_are_normalized_the_same_way_lookups_are() -> None:
    """表里的键必须是**小写、不带厂商前缀**的 —— 查表时先归一化,键没归一化就永远查不中。"""
    for prefix in KNOWN_LIMITS:
        assert prefix == prefix.lower().strip(), f"{prefix} 不是小写"
        assert "/" not in prefix, f"{prefix} 带了厂商前缀:查表前会被 rsplit 掉,这条永远匹配不上"


def test_numbers_are_rounded_down_not_up() -> None:
    """「宁可报小」:窗口报小只是早一点压缩,报大是整轮对话被拒。

    判据取成「整千」—— 真实上限几乎都是 2 的幂或它的倍数(1,048,576 / 131,072 / 393,216),
    一个没取整的数说明是照抄的原始值,而照抄就有报大的风险。
    """
    for prefix, limits in KNOWN_LIMITS.items():
        for name, value in (("窗口", limits.context_window), ("输出", limits.max_output_tokens)):
            if value is not None:
                assert value % 1000 == 0, f"{prefix} 的{name} {value} 没有向下取整到整千"


def test_output_never_exceeds_the_window() -> None:
    for prefix, limits in KNOWN_LIMITS.items():
        if limits.context_window and limits.max_output_tokens:
            assert limits.max_output_tokens <= limits.context_window, f"{prefix} 的输出上限比窗口还大"


@pytest.mark.parametrize(
    ("model_id", "expected_window"),
    [
        ("deepseek-v4-flash", 1_000_000),
        ("deepseek/deepseek-v4-pro", 1_000_000),  # OpenRouter 的 `厂商/` 前缀
        ("claude-haiku-4-5-20251001", 200_000),  # 日期后缀由前缀匹配天然覆盖
        ("Claude-Opus-5", 1_000_000),  # 大小写
        ("grok-4.6", 500_000),
        ("grok-4.3", 1_000_000),
    ],
)
def test_lookup_handles_the_id_shapes_we_actually_see(model_id: str, expected_window: int) -> None:
    assert known_limits(model_id).context_window == expected_window


def test_unknown_model_gets_nothing_rather_than_a_guess() -> None:
    assert known_limits("some-private-finetune-v3") == model_limits.Limits()
    assert known_limits("") == model_limits.Limits()


def test_catalog_beats_the_builtin_table() -> None:
    """目录是这个端点**自己**的说法:中转商把 1M 的模型限到 128K 时,该听它的。"""
    resolved = model_limits.resolve(
        model_id="deepseek-v4-flash",
        base_url="https://relay.example.com/v1",
        vendor="openai-compatible",
        catalog_window=128_000,
    )
    assert resolved.context_window == 128_000
    assert resolved.context_window_source == "catalog"


def test_builtin_table_beats_the_fallback() -> None:
    """用户撞到的那一条:目录不报上限时,别再把 1M 的模型当成 128K。"""
    resolved = model_limits.resolve(
        model_id="deepseek-v4-flash", base_url="https://api.deepseek.com/v1", vendor="deepseek"
    )
    assert resolved.context_window == 1_000_000
    assert resolved.context_window_source == "builtin"
    assert resolved.effective_max_output_tokens == OUTPUT_BUDGET_CAP


def test_user_override_is_not_capped() -> None:
    """「最大输出 Token」那一格存在的意义就是突破默认预算 —— 再给它封顶等于那一格没接线。"""
    resolved = model_limits.resolve(
        model_id="deepseek-v4-flash",
        base_url="https://api.deepseek.com/v1",
        vendor="deepseek",
        override_output=200_000,
    )
    assert resolved.max_output_tokens_source == "override"
    assert resolved.effective_max_output_tokens == 200_000


def test_local_endpoint_still_gets_the_conservative_window() -> None:
    resolved = model_limits.resolve(
        model_id="some-local-gguf", base_url="http://127.0.0.1:11434/v1", vendor="openai-compatible"
    )
    assert resolved.effective_context_window == 32_000
    assert resolved.context_window_source == "fallback"


def test_unknown_cloud_model_keeps_the_conservative_fallback() -> None:
    """表里没有 = 我们对这个端点一无所知。这里给大了就是整轮 400,所以仍然保守。"""
    resolved = model_limits.resolve(
        model_id="mystery-1", base_url="https://api.example.com/v1", vendor="openai-compatible"
    )
    assert resolved.effective_context_window == FALLBACK_CONTEXT_WINDOW
    assert resolved.effective_max_output_tokens == 4096
