"""直连对话补全走流式:长输出不会被供应商前面的网关掐断,读回来的仍是同一个回复体。

## 现场

漫剧第 2 场跑 CommandCode(OpenAI 兼容直连),20 镜的分镜一次要生成好几分钟。非流式时连接上一个字节都没有,
供应商前面的 Cloudflare 等满 100 秒就回 524「Upstream model provider is temporarily unavailable」—— 分镜节点连挂两次,
每次都在 126 秒上。看起来像供应商抽风,其实是我们的请求形状注定撑不过 100 秒。

流式时字节一边生成一边回来,网关不判超时;我们照样读完整段再拼成非流式的形状,计量、空内容降级、报错都不用变。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core import http_retry
from app.domain.ai_chat import AiChatError, ChatTarget, chat
from app.domain.billing.usage import BillableCall
from tests.util import module_time

TARGET = ChatTarget(base_url="https://provider.test", api_key="k", model="m")


def _sse(*chunks: dict | str) -> str:
    return "".join(f"data: {chunk if isinstance(chunk, str) else json.dumps(chunk)}\n\n" for chunk in chunks)


def _install(monkeypatch, response_for, seen: list[dict]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return response_for(request)

    real = http_retry.RetryingClient
    monkeypatch.setattr(http_retry, "RetryingClient", lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(http_retry, "time", module_time(sleep=lambda *a, **k: None))


def test_请求要流式下发_并且要用量(monkeypatch) -> None:
    seen: list[dict] = []
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, json={"choices": [{"message": {"content": "ok"}}]}), seen)

    chat(TARGET, [{"role": "user", "content": "hi"}])

    assert seen[0]["stream"] is True, "非流式时长输出撑不过网关的 100 秒"
    assert seen[0]["stream_options"] == {"include_usage": True}, "流式下不显式要,就拿不到用量、账记不上"


def test_流式分片拼回整段内容_用量照样计入(monkeypatch) -> None:
    body = _sse(
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"reasoning_content": "想一想"}}]},  # 推理过程不进正文
        {"choices": [{"delta": {"content": "第一镜,"}}]},
        {"choices": [{"delta": {"content": "沈青禾跪在供桌前。"}}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}},
        "[DONE]",
    )
    seen: list[dict] = []
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, text=body, headers={"content-type": "text/event-stream"}), seen)
    metered: list[dict] = []
    call = BillableCall.__new__(BillableCall)
    call.describe = lambda **kw: None  # type: ignore[method-assign]
    call.meter_openai_tokens = metered.append  # type: ignore[method-assign]

    text = chat(TARGET, [{"role": "user", "content": "写分镜"}], call=call)

    assert text == "第一镜,沈青禾跪在供桌前。"
    assert metered == [{"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 46}]


def test_流的中途报错就是失败_不拿半截内容当结果(monkeypatch) -> None:
    body = _sse({"choices": [{"delta": {"content": "第一镜"}}]}, {"error": {"message": "upstream overloaded"}})
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, text=body, headers={"content-type": "text/event-stream"}), [])

    with pytest.raises(AiChatError) as caught:
        chat(TARGET, [{"role": "user", "content": "写分镜"}])

    assert "upstream overloaded" in str(caught.value)


def test_JSON到了长度上限_截回最后一个完整元素再从下一个写起(monkeypatch) -> None:
    """CommandCode 上的 DeepSeek V4 Flash 每次三万来个 token 就停(请求里写 64000 也一样),20 镜的 3D 布景写不完。
    让它「从断开的那个字符接着写」不可靠 —— 实测它从下一个完整对象写起,接缝处那半个对象成了乱码。截到最后一个完整元素
    之后、请它从下一个元素写起。"""
    answers = [
        _sse({"choices": [{"delta": {"content": '{"shots": [{"id": "shot-1"}, {"id": "sh'}}]},
             {"choices": [{"delta": {}, "finish_reason": "length"}]}, "[DONE]"),
        _sse({"choices": [{"delta": {"content": '{"id": "shot-2"}]}'}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}, "[DONE]"),
    ]
    seen: list[dict] = []
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, text=answers[len(seen) - 1],
                                                   headers={"content-type": "text/event-stream"}), seen)

    text = chat(TARGET, [{"role": "user", "content": "搭布景"}], json_object=True, continue_cut_off=3)

    assert json.loads(text) == {"shots": [{"id": "shot-1"}, {"id": "shot-2"}]}
    follow = seen[1]
    assert follow["messages"][-2] == {"role": "assistant", "content": '{"shots": [{"id": "shot-1"},'}, "截掉了半个元素"
    assert "从下一个元素接着写" in follow["messages"][-1]["content"]
    assert "response_format" not in follow, "半截内容本身不是合法 JSON,续写时还强制 JSON 模式只会让模型另起一个对象"


def test_续写几次都从截断前那份请求出发_对话不越叠越长(monkeypatch) -> None:
    answers = [
        {"choices": [{"message": {"content": "第一段"}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "第二段"}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "第三段"}, "finish_reason": "stop"}]},
    ]
    seen: list[dict] = []
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, json=answers[len(seen) - 1]), seen)

    assert chat(TARGET, [{"role": "user", "content": "写长文"}], continue_cut_off=3) == "第一段第二段第三段"
    assert [len(one["messages"]) for one in seen] == [1, 3, 3]
    assert seen[2]["messages"][1] == {"role": "assistant", "content": "第一段第二段"}, "文字从断开的那个字接,不截"


def test_没开续写的照旧交回截断的那段(monkeypatch) -> None:
    body = _sse({"choices": [{"delta": {"content": "写到一半"}, "finish_reason": "length"}]}, "[DONE]")
    seen: list[dict] = []
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, text=body, headers={"content-type": "text/event-stream"}), seen)

    assert chat(TARGET, [{"role": "user", "content": "hi"}]) == "写到一半"
    assert len(seen) == 1


def test_整个JSON的回答也认得长度截断(monkeypatch) -> None:
    answers = [
        {"choices": [{"message": {"content": "前半"}, "finish_reason": "length"}]},
        {"choices": [{"message": {"content": "后半"}, "finish_reason": "stop"}]},
    ]
    seen: list[dict] = []
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, json=answers[len(seen) - 1]), seen)

    assert chat(TARGET, [{"role": "user", "content": "hi"}], continue_cut_off=1) == "前半后半"


def test_正文里的行分隔符不会把一条分片切成两半(monkeypatch) -> None:
    """SSE 只按 \\n 分行;此前用 splitlines(),正文里出现 U+2028 / \\x85 就把那一条 data 切断、整轮报格式错误。"""
    body = "data: " + json.dumps({"choices": [{"delta": {"content": "甲 乙\x85丙"}}]}, ensure_ascii=False) + "\n\ndata: [DONE]\n\n"
    _install(monkeypatch, lambda r: httpx.Response(200, request=r, text=body, headers={"content-type": "text/event-stream"}), [])

    assert chat(TARGET, [{"role": "user", "content": "hi"}]) == "甲 乙\x85丙"
