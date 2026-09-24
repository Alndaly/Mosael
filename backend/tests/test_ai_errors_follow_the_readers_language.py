"""供应商、本机运行环境、智能体 sidecar 的报错,**按读的人的语言**说。

此前这些是写死的中文句子:英文界面里弹出来的是中文,中间还夹着上游原样透传的英文
(「Evolink 请求失败: Client error '401 Unauthorized'…」)。现在领域里只说「是哪一种」+ 参数,
上游的原话放进 `detail`,出口按请求方的语言翻 —— 这里钉住英文那一面真的出得来。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.core.i18n import get_current_locale, set_current_locale, translate_fields


@pytest.fixture
def english():
    before = get_current_locale()
    set_current_locale("en")
    try:
        yield
    finally:
        set_current_locale(before)


def test_上游的原话放进翻好的句子里(english) -> None:
    from app.ai.providers.contracts.generation import adapter_http_error

    request = httpx.Request("POST", "https://api.example.test/v1/videos")
    response = httpx.Response(401, request=request, text='{"error":"invalid key sk-secret"}')
    error = adapter_http_error("Evolink", httpx.HTTPStatusError("401", request=request, response=response), "sk-secret")

    assert error.key == "providerErr_requestFailed"
    message = str(error)
    assert message.startswith("Evolink request failed: "), message
    assert "invalid key" in message, "上游那句是排查的依据,不能丢"
    assert "sk-secret" not in message, "脱敏照旧"

    set_current_locale("zh")
    assert str(error).startswith("Evolink 请求失败:")


def test_轮询超时带上是哪一家和远端任务号(english) -> None:
    from app.ai.providers.contracts.generation import GenerationAdapterError, poll_until_ready

    class _Running:
        def get(self, _path):
            return httpx.Response(200, json={"status": "running"}, request=httpx.Request("GET", "https://x.test"))

    with pytest.raises(GenerationAdapterError) as err:
        poll_until_ready(_Running(), "/tasks/cgt-9", lambda _p: None, interval=0, timeout=0, vendor="MiniMax")
    assert str(err.value) == "MiniMax generation timed out (remote task /tasks/cgt-9 did not finish within 0 h)"


def test_播客的前置检查说英文(english) -> None:
    from app.ai.providers.adapters.bytedance.volcano import podcast

    with pytest.raises(podcast.PodcastSynthesisError) as err:
        podcast.synthesize_volcano_podcast("", "")
    assert "App ID" in str(err.value) and "Access Token" in str(err.value)
    assert not any("一" <= ch <= "鿿" for ch in str(err.value)), str(err.value)


def test_任务失败原因记的是_key_而不是冻住的中文() -> None:
    """后台线程里抛的错,`str(exc)` 是缺省语言;落库的 key + 参数让接口按读的人的语言重翻。"""
    from app.ai.providers.contracts.speech import SpeechSynthesisError
    from app.core.i18n import render_message
    from app.domain.jobs import blame

    failed = blame(SpeechSynthesisError("providerErr_ttsFailed", engine="OpenAI", detail="HTTP 429"))
    assert failed["error_key"] == "providerErr_ttsFailed"
    assert render_message(failed["error_key"], "en", failed["error_params"]) == "OpenAI speech synthesis failed: HTTP 429"


def test_装不上的原因存_key_出口再翻() -> None:
    from app.ai.runtime.errors import RuntimeSetupError, failure_message, with_log

    message, params = failure_message(RuntimeSetupError("runtimeErr_depsFailed", engine="demucs", detail="pip exited 1"))
    row = {"message": message, "message_params": params}
    assert translate_fields(row, ("message",), "en")["message"] == (
        "Could not install the demucs runtime dependencies: pip exited 1"
    )
    # 第三方自己的那句话翻不了,原样带出来。
    assert failure_message(RuntimeError("No space left on device")) == ("No space left on device", {})

    # 「完整日志:…」那半句也跟着语言走,而不是拼死在原因后面。
    message, params = with_log("ModuleNotFoundError: No module named 'natsort'", {}, "/tmp/run.log")
    shown = translate_fields({"message": message, "message_params": params}, ("message",), "en")["message"]
    assert shown == "ModuleNotFoundError: No module named 'natsort'\nFull log: /tmp/run.log"


def test_worker_报的_key_由宿主翻(english) -> None:
    """worker 跑在隔离解释器里、import 不了文案表:它只报 key,宿主来翻。"""
    from app.ai.runtime.worker_pool import ResidentWorker
    from app.ai.runtime.workers.line_protocol import KeyedWorkerError, error_event

    event = error_event(KeyedWorkerError("runtimeErr_fishNeedsReference", "Fish Speech needs reference audio"))
    assert event["key"] == "runtimeErr_fishNeedsReference"
    failure = ResidentWorker._failure(SimpleNamespace(_kind="tts"), event)
    assert str(failure) == "Fish Speech needs reference audio"
    # 引擎自己的原话不带 key:原样交出去。
    raw = ResidentWorker._failure(SimpleNamespace(_kind="tts"), {"event": "error", "message": "CUDA out of memory"})
    assert str(raw) == "CUDA out of memory"


def test_分离_worker_写在结果文件里的原因按语言翻(english, tmp_path) -> None:
    from app.ai.providers.adapters.local.demucs_separation import _worker_failure

    result = tmp_path / "result.json"
    result.write_text(json.dumps({"error": {"key": "providerErr_separationOnlyVocals", "params": {"model": "htdemucs"}}}))
    completed = SimpleNamespace(returncode=1, stderr="providerErr_separationOnlyVocals {}", stdout="")
    assert str(_worker_failure(result, completed)) == (
        "htdemucs produced only the vocal track, with nothing to build the background from"
    )

    result.write_text("")
    crashed = SimpleNamespace(returncode=-9, stderr="", stdout="")
    assert str(_worker_failure(result, crashed)) == "Separation failed (exit code -9)"


def test_分离_worker_真跑一次_报的是_key(english, tmp_path) -> None:
    """worker 真的在一个子进程里跑(找不到音频那一步不需要 demucs):原因经结果文件回到宿主。"""
    import subprocess
    import sys

    from app.ai.providers.adapters.local.demucs_separation import _worker_failure
    from app.ai.runtime import workers

    result = tmp_path / "result.json"
    missing = tmp_path / "nope.wav"
    completed = subprocess.run(
        [sys.executable, str(workers.separation_script()), str(result)],
        input=json.dumps({"audio_path": str(missing), "out_dir": str(tmp_path / "out")}),
        capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode != 0
    assert str(_worker_failure(result, completed)) == f"Could not find the audio to separate: {missing}"


def test_智能体没配供应商时说英文(english) -> None:
    from app.ai.sidecar import adapters

    with pytest.raises(adapters.AdapterError) as err:
        adapters.compact_session(api_base="", token="", provider=None, model=None, adapter_state=None)
    assert str(err.value) == "No AI provider is available. Add and enable one in Settings."


def test_接口按_Accept_Language_回英文(monkeypatch) -> None:
    """走一遍真实的请求:中间件把语言放进 ContextVar,路由的 `detail=str(exc)` 就是英文。"""
    from app.ai.runtime import denoise_models
    from tests.util import fresh_client

    monkeypatch.setattr(denoise_models, "deepfilter_binary_spec", lambda: None)
    client = fresh_client()
    english = client.post("/api/denoise/engines/deepfilternet/install", headers={"Accept-Language": "en-US"})
    assert english.status_code == 409, english.text
    assert english.json()["detail"] == "DeepFilterNet has no release build for this platform"

    chinese = client.post("/api/denoise/engines/deepfilternet/install", headers={"Accept-Language": "zh-CN"})
    assert chinese.json()["detail"] == "这个平台没有 DeepFilterNet 的发布文件"
