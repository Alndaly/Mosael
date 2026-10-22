"""Command Code:一把订阅计划的 Key,走 OpenAI 兼容通道。

和现有那些「订阅计划」供应商(Anthropic Pro/Max、ChatGPT Codex、GitHub Copilot、Kimi Code)比,
它有两处不一样,**这两处正是这条测试要钉的**:

1. **鉴权是 API Key,不是 OAuth** —— 订阅买完在供应商的 Studio 里生成 Key,同一个 Key 认证 CLI 和
   Provider API。所以它不进 pi 那一组(没有 `pi_provider`),走 api_key 那一档。
2. **目录里混着只认 `/messages` 的 Claude** —— 本应用只有 OpenAI 兼容那两条路(`/chat/completions`、
   `/responses`)。不过滤的话,模型列表里会摆出一排"选了必然 400"的条目。
"""
from __future__ import annotations

import httpx
import pytest

from app.ai import model_catalog
from app.ai.model_catalog import clear_cache, fetch_models
from app.domain.providers.presets import catalog_protocol, provider_definition
from tests.util import stub_client

BASE = "https://api.commandcode.ai/provider/v1"


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    clear_cache()
    yield
    clear_cache()


def _stub(monkeypatch, payload: object, *, calls: list | None = None) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        if calls is not None:
            calls.append((url, kwargs.get("headers")))
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(model_catalog, "RetryingClient", stub_client(get=fake_get))


def test_the_preset_is_an_api_key_subscription_not_a_pi_provider() -> None:
    definition = provider_definition("command-code")
    assert definition is not None, "Command Code 没登记进预设表"
    assert definition.auth_types == ("api_key",), "它是 Studio 里生成的 Key,不是 OAuth"
    assert definition.pi_provider == "", "pi 不承载它 —— 走本应用自己的 OpenAI 兼容通道"
    assert definition.base_url == BASE
    assert definition.capability_ids == ("chat",)
    assert catalog_protocol("command-code") == "command-code", "目录要按 supported_endpoints 过滤"
    # 用户要做的是粘一把 Key,不是去填一堆端点。
    keys = [field.key for field in definition.fields]
    assert keys[0] == "api_key"
    assert definition.field("api_key").required is True  # type: ignore[union-attr]
    assert definition.field("base_url").default == BASE  # type: ignore[union-attr]


def test_only_models_this_app_can_reach_survive(monkeypatch) -> None:
    """Claude 只认 `/messages` → 剔掉;其余按 supported_endpoints 留;窗口照旧读 context_length。"""
    calls: list[tuple[str, object]] = []
    _stub(
        monkeypatch,
        {"object": "list", "data": [
            {"id": "claude-sonnet-5", "context_length": 1000000, "supported_endpoints": ["/messages"]},
            {"id": "gpt-6.1-sol", "context_length": 1050000, "supported_endpoints": ["/chat/completions", "/responses"]},
            {"id": "deepseek/deepseek-v4.1-flash", "context_length": 1000000, "supported_endpoints": ["/chat/completions", "/responses"]},
            {"id": "qwen-only-responses", "context_length": 200000, "supported_endpoints": ["/responses"]},
            {"id": "legacy-no-endpoints", "context_length": 8192},
        ]},
        calls=calls,
    )
    models = {model.id: model for model in fetch_models(BASE, "cmd-key", protocol="command-code")}
    assert "claude-sonnet-5" not in models, "Claude 只认 /messages,本应用发不出去"
    assert models["gpt-6.1-sol"].context_window == 1050000
    assert models["qwen-only-responses"].context_window == 200000
    # 没有 supported_endpoints 的条目照收:别家目录都没有这个字段,不能因此把它们全丢了。
    assert models["legacy-no-endpoints"].context_window == 8192
    assert calls and calls[0][0] == f"{BASE}/models"
