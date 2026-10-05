"""火山方舟的内容审核拦下请求时说人话:是哪一样被拦、这是服务商的审核不是 Mosael 拦的、下一步怎么办。

隔离环境里跑「模特上身图」:上身图当首帧交给 Seedance,方舟回 400
`InputImageSensitiveContentDetected.PrivacyInformation`(首帧里可能有真人)。用户看到的是
「ARK 请求失败:Client error '400 Bad Request' f…」—— 一句截断的英文,看不出是服务商的审核,也不知道换 Evolink 上的
Seedance 就能出(真跑过:同一张首帧 Evolink 照常出片)。同一类的审核码(提示词、生成结果、别的素材)一起翻。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.ai.providers.adapters.bytedance.ark.image import SeedreamAdapter
from app.ai.providers.adapters.bytedance.ark.video import SeedanceAdapter
from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationAdapterError, GenerationRequest
from app.core.http_retry import RetryingClient
from app.core.i18n import render_message


def _route(monkeypatch, module: str, handler) -> None:
    transport = httpx.MockTransport(handler)

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return RetryingClient(*args, **kwargs)

    monkeypatch.setattr(f"app.ai.providers.adapters.bytedance.ark.{module}.RetryingClient", patched)


def _rejected(code: str, message: str = "The request failed because the input may contain sensitive information."):
    return lambda request: httpx.Response(400, json={"error": {"code": code, "message": message, "type": "BadRequest"}})


def _said(exc: GenerationAdapterError, locale: str) -> str:
    return render_message(exc.key, locale, exc.params)


def _seedance(tmp_path: Path) -> GenerationAdapterError:
    request = GenerationRequest(kind="video", model="doubao-seedance-2-0-260128", prompt="她慢慢转身",
                                parameters={"duration_seconds": 4, "resolution": "480p"})
    with pytest.raises(GenerationAdapterError) as caught:
        SeedanceAdapter().generate(request, GenerationAdapterContext("p", "bytedance", "k"), tmp_path)
    return caught.value


def test_首帧里有真人_说清是方舟的审核_不是_Mosael_拦的_建议换_Evolink_的_Seedance(tmp_path, monkeypatch) -> None:
    _route(monkeypatch, "video", _rejected("InputImageSensitiveContentDetected.PrivacyInformation",
                                           "The request failed because the input image may contain real person."))
    exc = _seedance(tmp_path)

    zh = _said(exc, "zh")
    assert "火山方舟" in zh and "真人" in zh and "输入的图片" in zh, zh
    assert "不是 Mosael" in zh and "Evolink" in zh and "Seedance" in zh, zh
    assert "InputImageSensitiveContentDetected.PrivacyInformation" in zh, "服务商的原码照带,方便对着它的文档查"
    en = _said(exc, "en")
    assert "Volcengine Ark" in en and "real person" in en and "not Mosael" in en and "Evolink" in en, en


def test_提示词被审核拦下_说是提示词的问题_改提示词再试(tmp_path, monkeypatch) -> None:
    _route(monkeypatch, "video", _rejected("InputTextSensitiveContentDetected"))
    zh = _said(_seedance(tmp_path), "zh")
    assert "火山方舟" in zh and "提示词" in zh and "不是 Mosael" in zh, zh


def test_生成的视频被审核拦下_任务失败时也说人话(tmp_path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-1"})
        return httpx.Response(200, json={"id": "cgt-1", "status": "failed", "error": {
            "code": "OutputVideoSensitiveContentDetected", "message": "The generated video may contain sensitive information."}})

    _route(monkeypatch, "video", handler)
    zh = _said(_seedance(tmp_path), "zh")
    assert "生成的视频" in zh and "不是 Mosael" in zh, zh


def test_任务失败但不是审核_照旧带上服务商给的原因(tmp_path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-1"})
        return httpx.Response(200, json={"id": "cgt-1", "status": "failed", "error": {
            "code": "InternalServiceError", "message": "The service encountered an unexpected internal error."}})

    _route(monkeypatch, "video", handler)
    exc = _seedance(tmp_path)
    assert exc.key == "providerErr_generationFailed"
    assert "InternalServiceError" in _said(exc, "zh"), "此前只说了一个 failed"


def test_出图的提示词被拦下_Seedream_也一样(tmp_path, monkeypatch) -> None:
    _route(monkeypatch, "image", _rejected("InputTextSensitiveContentDetected"))
    request = GenerationRequest(kind="image", model="doubao-seedream-4-0-250828", prompt="一只猫")
    with pytest.raises(GenerationAdapterError) as caught:
        SeedreamAdapter().generate(request, GenerationAdapterContext("p", "bytedance", "k"), tmp_path)
    zh = _said(caught.value, "zh")
    assert "火山方舟" in zh and "提示词" in zh, zh


def test_不是审核的_400_照旧是请求失败加原文(tmp_path, monkeypatch) -> None:
    _route(monkeypatch, "video", _rejected("InvalidParameter", "The parameter `duration` specified in the request is not valid."))
    exc = _seedance(tmp_path)
    assert exc.key == "providerErr_requestFailed"
    assert "InvalidParameter" in _said(exc, "zh")
