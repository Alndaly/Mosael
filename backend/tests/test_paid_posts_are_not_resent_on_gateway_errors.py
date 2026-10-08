"""付费的 POST 遇到网关 5xx 不再重发(ADR 0019 修订:重发规则看方法)。

500 / 502 / 504 / Cloudflare 52x 说的是「中间某一层没等到回答」,不是「源站没做」:中转站在 Cloudflare 后面跑一张慢图,
源站过 100 秒还没答,CF 回 524,源站照样把图做完、照样扣费。此前 RetryingClient 遇 5xx 一律重发 —— 一次点击最多扣四次;
异步提交遇网关 502 建出两个远端任务,只有后一个被跟踪。

只有对方明说「没处理这一次」的 429 / 503 / 529,非幂等请求才重发;幂等的 GET(轮询)照旧遇 5xx 就重发。
不调真实接口:真实适配器 + httpx.MockTransport。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationAdapterError, GenerationRequest
from app.core import http_retry


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    import app.ai.providers.adapters.shared.polling as polling

    monkeypatch.setattr(http_retry.time, "sleep", lambda *_: None)
    monkeypatch.setattr(polling.time, "sleep", lambda *_: None)


def _route(module, monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class Routed(module.RetryingClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "RetryingClient", Routed)


def test_同步生图遇中转站_524_只付一次(monkeypatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.openai import image as openai_image

    posts: list[str] = []
    png = base64.b64encode(b"\x89PNG fake").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(request.url.path)
        if len(posts) < 3:
            return httpx.Response(524, text="A timeout occurred")
        return httpx.Response(200, json={"data": [{"b64_json": png}]})

    _route(openai_image, monkeypatch, handler)
    with pytest.raises(GenerationAdapterError):
        openai_image.OpenAIImageAdapter("openai-compatible").generate(
            GenerationRequest(kind="image", model="gpt-image-1", prompt="一只猫", parameters={"num_images": 1}),
            GenerationAdapterContext(connection_id=None, vendor_id="openai-compatible", api_key="k",
                                     base_url="https://relay.example/v1", options={}),
            tmp_path,
        )
    assert posts == ["/v1/images/generations"], "源站照做照扣的 524 被重发了"


def test_异步视频提交遇网关_502_只建一个远端任务(monkeypatch, tmp_path: Path) -> None:
    from app.ai.providers.adapters.bytedance.ark import video as ark

    posts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(request.url.path)
            if len(posts) == 1:
                return httpx.Response(502, text="Bad Gateway")
            return httpx.Response(200, json={"id": f"cgt-{len(posts)}"})
        return httpx.Response(200, json={"status": "succeeded", "content": {"video_url": "https://tos/x.mp4"}})

    _route(ark, monkeypatch, handler)
    monkeypatch.setattr(ark, "download_to_path", lambda url, target, **kw: target.write_bytes(b"mp4"))
    with pytest.raises(GenerationAdapterError):
        ark.SeedanceAdapter().generate(
            GenerationRequest(kind="video", model="doubao-seedance-2-0-260128", prompt="p", parameters={}),
            GenerationAdapterContext(connection_id=None, vendor_id="bytedance", api_key="k", base_url="", options={}),
            tmp_path,
        )
    assert len(posts) == 1, "网关 502 之后又提交了一次,远端多了一个没人跟踪的付费任务"


@pytest.mark.parametrize("status", [500, 502, 504, 520, 522, 524])
def test_POST_遇到不能确定没处理的_5xx_不重发(monkeypatch, status: int) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(status)

    transport = httpx.MockTransport(handler)
    with http_retry.RetryingClient(max_retries=3, transport=transport) as client:
        assert client.post("https://provider.test/submit", json={}).status_code == status
    assert calls == ["POST"]


@pytest.mark.parametrize("status", [429, 503, 529])
def test_POST_遇到明说没处理的状态码照旧重发(monkeypatch, status: int) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(status) if len(calls) == 1 else httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    with http_retry.RetryingClient(max_retries=3, transport=transport) as client:
        assert client.post("https://provider.test/submit", json={}).status_code == 200
    assert calls == ["POST", "POST"]


@pytest.mark.parametrize("status", [500, 502, 504, 524])
def test_幂等的_GET_遇_5xx_照旧重发(monkeypatch, status: int) -> None:
    """轮询是 GET:重发不会多做一遍,网关抖一下照旧重试。"""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(status) if len(calls) == 1 else httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    with http_retry.RetryingClient(max_retries=3, transport=transport) as client:
        assert client.get("https://provider.test/tasks/1").status_code == 200
    assert calls == ["GET", "GET"]
