"""AI 供应商瞬断/限流/过载时自动重试,4xx 立即失败;最大重试次数可在设置页配置。

背景:供应商偶发「Server disconnected without sending a response」等网络瞬断,旧实现一次就把
整条工作流判失败(真丢过一条,28 秒后同参数重试即成功)。这里锁定重试语义 + 可配置次数。

重试现在做在传输层(domain/ai_retry.RetryingClient),**所有 AI 出站调用共用** —— 生图、
生视频、语音、向量化此前一次都不重试,而设置页那句话读起来管的是全部。所以打桩点也从
`httpx.post` 迁到了传输:绕过 RetryingClient 的打桩等于把被测逻辑一起绕过去。
"""

from __future__ import annotations

import httpx
import pytest

from app.core.db import SessionLocal
from app.db.models import AiRuntimeConfig
from app.domain.ai_chat import AiChatError, ChatTarget, chat
from app.core import http_retry as ai_retry
from app.domain.workflows.executors import ai
from tests.util import fresh_client


def _target() -> ChatTarget:
    return ChatTarget(base_url="https://provider.test", api_key="key", model="m")


def _req() -> httpx.Request:
    return httpx.Request("POST", "https://provider.test/chat/completions")


def _ok() -> httpx.Response:
    return httpx.Response(200, request=_req(), json={"choices": [{"message": {"content": "ok"}}]})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ai_retry.time, "sleep", lambda *a, **k: None)  # 别在测试里真退避


def _install(monkeypatch, handler) -> None:
    """把 RetryingClient 的传输换成 MockTransport。handler 抛异常即模拟连接层错误。"""
    transport = httpx.MockTransport(handler)
    real = ai_retry.RetryingClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    # 只打 ai_retry 一处就够:LLM 节点现在经 domain/ai_chat 走 ai_retry.post,
    # 而 ai_retry.post 是在自己的模块命名空间里 new 的 RetryingClient。
    monkeypatch.setattr(ai_retry, "RetryingClient", patched)


def test_transient_disconnect_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=_req())
        return _ok()

    _install(monkeypatch, handler)
    text = chat(_target(), [{"role": "user", "content": "hi"}], max_retries=3)
    assert calls["n"] == 3  # 前 2 次瞬断,第 3 次成功(在 3 重试=4 次尝试的额度内)
    assert text == "ok"


def test_gives_up_after_max_retries(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=_req())

    _install(monkeypatch, handler)
    with pytest.raises(AiChatError) as ei:
        chat(_target(), [{"role": "user", "content": "hi"}], max_retries=3)
    assert calls["n"] == 4  # 首次 + 3 次重试
    assert "网络/连接" in str(ei.value) and "重试 3 次" in str(ei.value)


def test_zero_retries_fails_immediately(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=_req())

    _install(monkeypatch, handler)
    with pytest.raises(AiChatError) as ei:
        chat(_target(), [{"role": "user", "content": "hi"}], max_retries=0)
    assert calls["n"] == 1  # 关掉重试就只尝试一次
    assert "重试" not in str(ei.value)  # 不显示「已重试 N 次」


def test_4xx_not_retried(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, request=_req(), json={"error": {"message": "bad request"}})

    _install(monkeypatch, handler)
    with pytest.raises(AiChatError) as ei:
        chat(_target(), [{"role": "user", "content": "hi"}], max_retries=3)
    assert calls["n"] == 1  # 4xx 是请求本身的问题,立即失败不重试
    assert "400" in str(ei.value)


def test_5xx_retried_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, request=_req(), json={"error": {"message": "overloaded"}})
        return _ok()

    _install(monkeypatch, handler)
    assert chat(_target(), [{"role": "user", "content": "hi"}], max_retries=3) == "ok"
    assert calls["n"] == 2


def test_configured_max_retries_reads_setting_and_clamps():
    fresh_client()  # 建库建表
    with SessionLocal() as db:
        assert ai.configured_max_retries(db) == 3  # 无行 → 缺省 3
        db.add(AiRuntimeConfig(id="default", max_retries=5))
        db.commit()
        assert ai.configured_max_retries(db) == 5
    with SessionLocal() as db:
        row = db.get(AiRuntimeConfig, "default")
        row.max_retries = 99  # 超范围
        db.commit()
        assert ai.configured_max_retries(db) == ai.MAX_RETRIES_CAP  # 夹到上限 10


def test_settings_endpoint_roundtrip():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 拥有工作区 → 满足 ensure_instance_admin
    assert client.get("/api/settings/ai-runtime").json()["max_retries"] == 3
    assert client.put("/api/settings/ai-runtime", json={"max_retries": 6}).json()["max_retries"] == 6
    assert client.get("/api/settings/ai-runtime").json()["max_retries"] == 6
    assert client.put("/api/settings/ai-runtime", json={"max_retries": 20}).status_code == 422  # 超范围拒绝


def test_重试对所有_AI_出站调用生效(monkeypatch):
    """这条锁的是本次改动的**要点**:重试原本只做在工作流 LLM 节点的 chat/completions 上,
    而设置页那句「AI 供应商…自动重试」读起来管的是全部 —— 生图、生视频、语音、向量化
    一次都不重试。现在同一个传输层被这些适配器共用,任何一处改回自己 new httpx.Client
    都会让这条红。"""
    import importlib

    from app.domain import ai_chat
    from app.core.http_retry import RetryingClient

    # **适配器不手写清单,自己走一遍目录。** 手写的话新加一家不会自动进来 —— 而"新加的那一家
    # 忘了走重试"正是这条测试要防的事,清单漏了它就等于这道闸对新代码不生效。
    # (2026-08-25 按能力重组目录时,手写清单里的路径也确实全部失效过一次。)
    import pkgutil

    import app.ai.providers as providers_pkg

    modules = [
        name
        for _, name, is_pkg in pkgutil.walk_packages(providers_pkg.__path__, f"{providers_pkg.__name__}.")
        # 包的 __init__ 是门面,只转发名字、不发请求;base 是契约,同理。
        # 用 walk_packages 给的 is_pkg 判断,而不是按名字猜 —— 猜的话新开一个包又要来改这里。
        if not is_pkg and not name.endswith(".base")
    ] + [
        "app.domain.generation.prompt_optimizer",
        "app.domain.workflows.ai_edit",
        "app.domain.analysis.service",
        "app.domain.workflows.executors.ai",
    ]
    #: 不发 HTTP 的适配器 —— 豁免要**逐个写清楚理由**,而不是放宽判据。
    #: 放宽的话下一个真绕过重试的也会一起溜过去。
    NO_HTTP = {
        # Edge 走 edge_tts 库(它自己开 WebSocket),这个模块里没有一次 HTTP 调用可以被包起来。
        "app.ai.providers.speech.edge",
    }

    #: **不自己建连接**的模块 —— 请求是拿调用方给的 client 发的,而那个 client 就是
    #: RetryingClient。豁免的理由和 NO_HTTP 不一样(那些是压根不发 HTTP),所以分开列:
    #: 判据也不同 —— 这些模块只要不 import httpx,就不可能绕开调用方给的那个 client。
    BORROWS_CLIENT = {
        # 可灵的主体库:建主体是生成流程里的一步,用的是 kling.py 已经开好的那个连接
        # (同一个 base_url、同一份 JWT 鉴权)。自己再开一个等于把鉴权逻辑抄第二遍。
        "app.ai.providers.video.kling_elements",
    }

    missing = []
    for name in modules:
        if name in BORROWS_CLIENT:
            module = importlib.import_module(name)
            assert not hasattr(module, "httpx"), f"{name} 自己发 HTTP 了,豁免不再成立"
            continue
        if name in NO_HTTP:
            module = importlib.import_module(name)
            assert not hasattr(module, "httpx"), f"{name} 开始发 HTTP 了,豁免不再成立"
            continue
        module = importlib.import_module(name)
        uses_client = getattr(module, "RetryingClient", None) is RetryingClient
        uses_helpers = getattr(module, "ai_retry", None) is not None
        # 对话类调用统一经 domain/ai_chat,而 ai_chat 自己走 ai_retry —— 也算接上了。
        uses_chat = getattr(module, "chat", None) is ai_chat.chat
        if not (uses_client or uses_helpers or uses_chat):
            missing.append(name)
    assert missing == [], f"这些模块绕过了统一重试:{missing}"


def test_设置写入即时生效不必重启(monkeypatch):
    """次数存进程级状态(调用点散在十几个适配器里,不少拿不到 db 会话)。
    与出站代理同一套做法:改完立刻生效。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # 拥有工作区 → 满足 ensure_instance_admin
    original = ai_retry.current_max_retries()
    try:
        response = client.put("/api/settings/ai-runtime", json={"max_retries": 7})
        assert response.status_code == 200
        assert ai_retry.current_max_retries() == 7
    finally:
        ai_retry.set_max_retries(original)


def test_次数夹在合法区间():
    original = ai_retry.current_max_retries()
    try:
        ai_retry.set_max_retries(-5)
        assert ai_retry.current_max_retries() == 0  # 0 = 不重试
        ai_retry.set_max_retries(99)
        assert ai_retry.current_max_retries() == 10
    finally:
        ai_retry.set_max_retries(original)
