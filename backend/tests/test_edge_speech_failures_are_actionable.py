"""Edge 免费语音握手被拒时,弹窗里那句话要**说得清、给得出路**。

维护者截图里那句:

    Edge 语音合成失败:403, message='Invalid response status',
    url='wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1
         ?TrustedClientToken=…&ConnectionId=…&Sec-MS-GEC=…'

整条 wss url、TrustedClientToken、Sec-MS-GEC 都进了弹窗,而「我该做什么」一个字没有。403
`Invalid response status` 是微软 read-aloud 端点拒绝 ``Sec-MS-GEC`` 令牌的典型回法(2026-10 那次
令牌从 v1 换成 v2,旧版 edge-tts 因此一律握手失败;修在上游,见 pyproject 里 edge-tts 的版本说明)。

这条用例钉住的是**再遇到同类拒绝时**用户读到的话:

- 带引擎名和真正的短原因(403 令牌校验);
- 不带长 url / 令牌 / 上游原文(那些进日志,给排查的人);
- 说得出下一步(更新 Mosael,或换一个语音引擎);
- 短到不会被出口的 ``[:300]`` 截断(见 routes/voices 的配音失败出口)。
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from app.ai.providers.adapters.microsoft import edge_speech
from app.ai.providers.adapters.microsoft.edge_speech import EdgeSpeechAdapter
from app.ai.providers.contracts.speech import SpeechSynthesisError, SpeechSynthesisRequest
from app.core.i18n import set_current_locale

#: 截图里那种 url(令牌和连接号照原样,形状不变)。
REJECTED_URL = (
    "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
    "?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4"
    "&ConnectionId=1b3fc36538cb4f29bfc2b08003d2cd4b&Sec-MS-GEC=5549BA658519CE&Sec-MS-GEC-Version=1-143.0.3650.75"
)
#: 弹窗里一个都不该出现的内部串。
INTERNALS = ("wss://", "TrustedClientToken", "ConnectionId", "Sec-MS-GEC", "Invalid response status")


def _handshake_error(status: int = 403) -> aiohttp.WSServerHandshakeError:
    url = URL(REJECTED_URL)
    request_info = aiohttp.RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)
    return aiohttp.WSServerHandshakeError(request_info, (), status=status, message="Invalid response status")


def _communicate_that_raises(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> list[str]:
    """把 edge_tts.Communicate 换成「一 save 就抛」的那一个,返回每次构造的参数(数重试次数用)。"""
    seen: list[str] = []

    class _Communicate:
        def __init__(self, text: str, voice: str = "", rate: str = "") -> None:
            seen.append(text)

        async def save(self, path: str) -> None:
            raise error

    import edge_tts

    monkeypatch.setattr(edge_tts, "Communicate", _Communicate)
    return seen


def _synthesize(tmp_path: Path) -> None:
    EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="你好", voice="zh-CN-XiaoxiaoNeural"), tmp_path / "a.mp3")


@pytest.fixture
def en():
    set_current_locale("en")
    try:
        yield
    finally:
        set_current_locale("zh")


def test_403_speaks_the_engine_reason_and_next_step(tmp_path, caplog, monkeypatch) -> None:
    set_current_locale("zh")
    _communicate_that_raises(monkeypatch, _handshake_error())

    with caplog.at_level(logging.WARNING, logger=edge_speech.__name__), pytest.raises(SpeechSynthesisError) as err:
        _synthesize(tmp_path)

    error = err.value
    assert error.key == "providerErr_edgeTtsRejected", "新的一句必须是文案表里的 key,不能是拼出来的中文"
    message = str(error)

    assert "Edge" in message, f"没说清是哪家引擎:{message}"
    assert "403" in message and "令牌" in message, f"没说清真正的短原因:{message}"
    for internal in INTERNALS:
        assert internal not in message, f"内部串漏进弹窗了({internal}):{message}"
    assert "更新" in message and "语音引擎" in message, f"这句话没给下一步:{message}"
    assert len(message) <= 300, f"出口会把失败原因截到 300 字,这句被截断后就不完整了:{len(message)}"

    # 长 url / 上游原文**进日志**:排查的人要它,读弹窗的人不要。
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert "wss://" in logged and "Sec-MS-GEC" in logged, logged


def test_403_speaks_english_too(en, tmp_path, monkeypatch) -> None:
    _communicate_that_raises(monkeypatch, _handshake_error())

    with pytest.raises(SpeechSynthesisError) as err:
        _synthesize(tmp_path)

    message = str(err.value)
    assert "Update Mosael" in message and "speech engine" in message, message
    assert "403" in message
    assert len(message) <= 300, f"出口会把失败原因截到 300 字,这句被截断后就不完整了:{len(message)}"
    for internal in INTERNALS:
        assert internal not in message, f"内部串漏进弹窗了({internal}):{message}"
    assert not any("一" <= ch <= "鿿" for ch in message), f"英文界面里冒出中文:{message}"


def test_token_rejection_is_not_retried(tmp_path, monkeypatch) -> None:
    """同一套令牌重连多少次都是同一个 403 —— 让它重试只会让人多等几轮再看到同一句话。"""
    monkeypatch.setattr(edge_speech, "current_max_retries", lambda: 3)
    seen = _communicate_that_raises(monkeypatch, _handshake_error())

    with pytest.raises(SpeechSynthesisError):
        _synthesize(tmp_path)

    assert len(seen) == 1, f"令牌被拒还重试了 {len(seen)} 次"


def test_network_blips_are_still_retried(tmp_path, monkeypatch) -> None:
    """别把「重试」一并删掉:超时 / 连不上仍然该再连,那是这个免费通道一直有的兜底。"""
    monkeypatch.setattr(edge_speech, "current_max_retries", lambda: 2)
    monkeypatch.setattr(edge_speech, "backoff_seconds", lambda _attempt: 0)
    seen = _communicate_that_raises(monkeypatch, TimeoutError("timed out"))

    with pytest.raises(SpeechSynthesisError) as err:
        _synthesize(tmp_path)

    assert len(seen) == 3, f"超时只试了 {len(seen)} 次"
    assert err.value.key == "providerErr_ttsFailed", "这一种仍走通用那句(带上游原话)"
