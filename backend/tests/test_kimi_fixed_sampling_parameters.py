"""Kimi K3/K2.7/K2.6 把采样参数钉死:请求里不能带 temperature 等键。

用户实际撞到的错误:

    invalid temperature: only 1 is allowed for this model

我们的 `chat()` 默认发 temperature=0.2,而所有调用点(素材分析、标题、工作流 LLM 节点)都经过它。
所以这条契约钉在请求构造处:同一个模型、同一次调用,payload 里没有 `temperature`;别的模型不受影响。
"""

from __future__ import annotations

import pytest

from app.domain import ai_chat


class _Response:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


def _capture(monkeypatch) -> dict:
    seen: dict = {}

    def fake_post(url: str, **kwargs):
        seen.update(kwargs["json"])
        return _Response({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(ai_chat.http_retry, "post", fake_post)
    return seen


@pytest.mark.parametrize("vendor,model", [
    ("moonshot", "kimi-k3"),
    ("moonshot", "kimi-k2.7-code"),
    ("openai-compatible", "kimi-k2.6"),
])
def test_kimi_fixed_sampling_parameters_are_not_sent(monkeypatch, vendor: str, model: str) -> None:
    seen = _capture(monkeypatch)
    target = ai_chat.ChatTarget(base_url="https://api.example.test/v1", api_key="sk-test", model=model, vendor=vendor)

    assert ai_chat.chat(target, [{"role": "user", "content": "hi"}], temperature=0.2,
                        extra={"top_p": 0.8}) == "ok"

    assert "temperature" not in seen
    assert "top_p" not in seen


def test_other_models_keep_their_temperature(monkeypatch) -> None:
    seen = _capture(monkeypatch)
    target = ai_chat.ChatTarget(base_url="https://api.example.test/v1", api_key="sk-test", model="gpt-4o", vendor="openai")

    ai_chat.chat(target, [{"role": "user", "content": "hi"}], temperature=0.2)

    assert seen["temperature"] == 0.2
