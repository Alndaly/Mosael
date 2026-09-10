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
