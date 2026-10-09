"""火山的两条连接此前永远「离线」:探针是 GET base_url + /models —— TTS 那边 /models 是 404,
播客那边 base_url 是 wss:// 根本没法 GET。现在定义里点名探针种类,实现住适配器。
"""

from __future__ import annotations

import pytest

from app.domain.providers.credentials import ResolvedConnection
from app.domain.providers.health import _PROBE_IMPLEMENTATIONS, probe
from app.domain.providers.presets import provider_definitions


def _conn(vendor: str, **over) -> ResolvedConnection:
    base = dict(id="p1", name="x", vendor=vendor, base_url="", auth_type="api_key", enabled=True)
    base.update(over)
    return ResolvedConnection(**base)


def test_声明的探针种类都登记了实现() -> None:
    declared = {d.health_probe for d in provider_definitions() if d.health_probe}
    assert declared == {"volcano_tts", "volcano_podcast"}
    assert set(declared) <= set(_PROBE_IMPLEMENTATIONS)


def test_tts_钥匙被拒是在线的凭据问题(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.providers.adapters.bytedance.volcano import speech

    class _Resp:
        status_code = 401

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            assert url.endswith("/api/v3/tts/unidirectional")
            assert kw["headers"]["X-Api-Key"] == "the-key"
            return _Resp()

    monkeypatch.setattr(speech, "RetryingClient", _Client)
    result = probe(_conn("volcano", base_url="https://openspeech.bytedance.com", api_key="the-key"))
    assert result.supported and result.online
    assert result.detail  # 凭据被拒那句话


def test_tts_钥匙收下了就在线(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ai.providers.adapters.bytedance.volcano import speech

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            return _Resp()

    monkeypatch.setattr(speech, "RetryingClient", _Client)
    result = probe(_conn("volcano", base_url="https://openspeech.bytedance.com", api_key="good"))
    assert result.online and not result.detail


def test_tts_连不上是离线(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.ai.providers.adapters.bytedance.volcano import speech

    class _Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, **kw):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(speech, "RetryingClient", _Client)
    result = probe(_conn("volcano", base_url="https://openspeech.bytedance.com", api_key="k"))
    assert result.supported and not result.online and result.detail


def test_podcast_握手401是凭据被拒(monkeypatch: pytest.MonkeyPatch) -> None:
    import websockets.exceptions

    class _Resp:
        status_code = 401

    class _Rejected:
        # websockets.connect() 返回的东西**直接**支持 async with(不是 coroutine),握手失败在 __aenter__ 里抛
        async def __aenter__(self):
            raise websockets.exceptions.InvalidStatus(_Resp())

        async def __aexit__(self, *a):
            return False

    def _connect(*a, **kw):
        return _Rejected()

    monkeypatch.setattr("websockets.connect", _connect)
    # 出站守卫的票:测试里不开代理服务,给一张假的
    class _Ticket:
        url = "http://unused"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import app.core.outbound_proxy as proxy_mod

    monkeypatch.setattr(proxy_mod, "ticket", lambda *a, **kw: _Ticket())
    result = probe(_conn("volcano-podcast", base_url="wss://openspeech.bytedance.com", api_key="tok", extra={"appid": "123"}))
    assert result.online and result.detail  # 凭据被拒


def test_podcast_握手成功是在线(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def _connect(*a, **kw):
        return _Socket()

    monkeypatch.setattr("websockets.connect", _connect)

    class _Ticket:
        url = "http://unused"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import app.core.outbound_proxy as proxy_mod

    monkeypatch.setattr(proxy_mod, "ticket", lambda *a, **kw: _Ticket())
    result = probe(_conn("volcano-podcast", base_url="wss://openspeech.bytedance.com", api_key="tok", extra={"appid": "123"}))
    assert result.online and not result.detail
