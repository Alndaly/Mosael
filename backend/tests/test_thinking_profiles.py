"""思考档位这张表**只写查证过的**,其余一律不声明。

用户报的是「选了关闭,Kimi k3 照样在思考」。查证(2026-09,Kimi 官方 API 文档)的结论是
k3 **一直思考**:`reasoning_effort` 只收 low/high/max,没有关闭这一说。所以正确的界面不是
"关闭没生效",而是**这个模型压根不提供关闭**。

这张表的风险在另一头:猜错一个值,发出去被端点拒掉,**整轮对话 400**——不是少一个增强。
所以判据是"有没有把握",查不到就不声明。
"""

from __future__ import annotations

from app.domain.thinking import LEVELS, UNKNOWN, profile_for


def test_kimi_k3_关不掉_而且没有中档() -> None:
    profile = profile_for("moonshot", "kimi-k3-preview")
    assert profile.can_disable is False
    # 官方只给 low / high / max —— 界面上给「中」等于给一个发出去会被拒的值。
    assert profile.levels() == ["low", "high"]
    assert profile.level_map["off"] is None
    assert profile.level_map["medium"] is None


def test_openai_可以关_而且关是一个真的值() -> None:
    profile = profile_for("openai", "gpt-5.1")
    assert profile.can_disable is True
    # 关闭对 OpenAI 来说是 reasoning_effort:"none",不是"什么都不发"。
    assert profile.level_map["off"] == "none"
    assert profile.levels() == list(LEVELS)


def test_查不到的一律不声明() -> None:
    # 少一个能用的开关,比一个点了会让对话失败的开关好。
    for vendor, model in [("alibaba", "qwen3-max"), ("deepseek", "deepseek-chat"), ("moonshot", "kimi-k2.6")]:
        profile = profile_for(vendor, model)
        assert profile.levels() == [], f"{vendor}/{model} 不该声明档位"
        assert profile is UNKNOWN or all(value is None for value in profile.level_map.values())


def test_不声明的表也说得出自己关不掉() -> None:
    # can_disable=False + 没有档位 = "这条连接发不出思考档位",而不是"这个模型不思考"。
    assert UNKNOWN.can_disable is False
    assert UNKNOWN.levels() == []


def test_查证过的那几家都发得出档位() -> None:
    """用户实测反馈:"很多应该支持的模型都没有档位选择"。

    此前表里只实现了 Kimi 和 OpenAI 两家,而模块头的查证结果列了六家 —— 看起来像漏了四家。
    实际上 qwen 和 GLM 是**发不出去**(它们不用 reasoning_effort),留空是对的;
    真正漏掉的是 DeepSeek 和 Grok,这两家用的就是 reasoning_effort。
    """
    assert profile_for("deepseek", "deepseek-v4-pro").levels() == ["low", "high"]
    assert profile_for("xai", "grok-4.3").levels() == ["low", "medium", "high"]
    # 都关不掉:DeepSeek 要发 thinking:{type:disabled} 才关得掉(这条路发不出),
    # Grok 的官方文档直接写了 "Reasoning cannot be disabled"。
    assert "off" not in profile_for("deepseek", "deepseek-v4-pro").levels()
    assert "off" not in profile_for("xai", "grok-4.3").levels()


def test_中转端点按模型名认家族() -> None:
    """第三方中转的 vendor 一律是 openai-compatible,按 vendor 查表必然落空。

    走中转配 gpt-5 的人不该因为"我们认不出这个 vendor"就一个档位都拿不到。
    """
    assert profile_for("openai-compatible", "gpt-5.2").levels() == ["off", "low", "medium", "high"]
    assert profile_for("openai-compatible", "deepseek-v4-pro").levels() == ["low", "high"]
    assert profile_for("openai-compatible", "grok-4.5").levels() == ["low", "medium", "high"]
    # 认不出的仍然不声明 —— 保守是这张表的立身之本。
    assert profile_for("openai-compatible", "gemma4").levels() == []


def test_用不了_reasoning_effort_的那两家不声明() -> None:
    """qwen 用 enable_thinking、GLM 用 thinking:{type},合成模型这条路发不出去。

    声明了等于给用户一个点了没反应的开关 —— 那比没有开关更坏。
    """
    assert profile_for("alibaba", "qwen3-max").levels() == []
    assert profile_for("zhipu", "glm-5").levels() == []
