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


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        # 家族兜底:表里没写 claude-opus-4-1,它仍拿得到 Claude 的保守下限,而不是掉回 128K。
        ("anthropic/claude-opus-4-1", 200_000),
        ("claude-3-5-sonnet-20241022", 200_000),
        # 具体型号盖掉兜底。
        ("claude-opus-4-8", 1_000_000),
        # 同代不同档:gpt-5.x 里 5.2 起才是 1M 一档。
        ("gpt-5.1-codex", 400_000),
        ("gpt-5.6-sol", 1_000_000),
        # 更长的那条赢,不是先匹配到的那条。
        ("qwen3-coder-flash", 1_000_000),
        ("qwen3-coder-2026", 256_000),
    ],
)
def test_longest_prefix_wins(model_id: str, expected: int) -> None:
    assert known_limits(model_id).context_window == expected


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


# ---------------------------------------------------------------------------
# 「发不出思考档位」≠「这个模型不思考」
# ---------------------------------------------------------------------------


class Test思考吃不吃输出额度:
    """`ThinkingProfile` 描述的是**我们能怎么控制它**,预算计算需要的是**它的行为是什么**。

    两个问题此前共用一个数据结构:`resolve` 拿 `level_map` 全是 None 推出「不思考」,
    于是任何一个没查证过思考格式的模型都拿到 4096 的非推理额度。而 `profile_for` 的文档
    **明写**了 qwen 和 GLM 不在表里「不是漏了」—— 是因为它们用的不是 `reasoning_effort`,
    我们这条路发不出去。**发不出去 ≠ 不思考。**

    受影响的是中转/本地端点上挂的推理模型:用户勾了「推理模型」、窗口也认出来了,
    输出额度还是 4096 —— 而 model_limits 模块头记的那个真实故障(一轮思考还没说完就报
    已用完输出额度)正是这么来的。
    """

    def test_勾了推理模型的未知模型_额度必须高于非推理档(self) -> None:
        from app.domain.model_limits import FALLBACK_MAX_OUTPUT_TOKENS, resolve

        kwargs = dict(model_id="my-custom-thinker", base_url="http://127.0.0.1:11434/v1",
                      vendor="openai-compatible")
        plain = resolve(**kwargs).effective_max_output_tokens
        ticked = resolve(**kwargs, reasoning=True).effective_max_output_tokens

        assert plain == FALLBACK_MAX_OUTPUT_TOKENS, "没勾时保守取非推理档,这条是对照"
        assert ticked > FALLBACK_MAX_OUTPUT_TOKENS, (
            "用户勾了「推理模型」,而输出额度还是非推理那一档 —— 一轮思考没说完就会报额度用尽"
        )

    def test_查证过会思考的_不用勾也算数(self) -> None:
        """qwen / GLM / r1 这类:我们发不出它们的档位,但它们确实在思考。"""
        from app.domain.model_limits import FALLBACK_MAX_OUTPUT_TOKENS, resolve

        for model in ("qwen3-235b", "deepseek-r1-distill-32b", "glm-4.6"):
            got = resolve(model_id=model, base_url="http://127.0.0.1:11434/v1",
                          vendor="openai-compatible").effective_max_output_tokens
            assert got > FALLBACK_MAX_OUTPUT_TOKENS, f"{model} 被当成了不思考"

    def test_查证过的结论压过用户的猜测(self) -> None:
        """勾不勾都一样 —— 查证过的行为比一个复选框更可信。"""
        from app.domain.model_limits import resolve

        kwargs = dict(model_id="qwen3-235b", base_url="http://127.0.0.1:11434/v1",
                      vendor="openai-compatible")
        assert (resolve(**kwargs).effective_max_output_tokens
                == resolve(**kwargs, reasoning=False).effective_max_output_tokens)

    def test_两个谓词回答的是两个问题(self) -> None:
        from app.domain.thinking import UNKNOWN, burns_output_budget, profile_for

        # qwen:发不出档位(UNKNOWN),但确实思考。这一对正是原先那个 bug 的形状。
        assert profile_for("openai-compatible", "qwen3-235b") is UNKNOWN
        assert burns_output_budget("openai-compatible", "qwen3-235b") is True
        # 真不知道的返回 None,**不是 False** —— False 会把用户勾的那一格盖掉。
        assert burns_output_budget("openai-compatible", "llama-3-70b") is None
