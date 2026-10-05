"""百炼 CosyVoice 的声音复刻适配器(ADR 0037):请求体、前缀长度、状态值。

**不打网络**:HTTP 换成 httpx 的 MockTransport,直传 OSS 那一下换成假的。风险全在「把四个动作翻成百炼的形状」和
「从回包里捞 voice_id、状态」—— 形状照 2026-10-05 真机验过的写。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.ai.providers import VoiceEnrollmentError, build_voice_enrollment_adapter
from app.ai.providers.adapters.alibaba.dashscope import uploads as temporary_storage
from app.ai.providers.adapters.alibaba.dashscope import voice_enrollment
from app.ai.providers.adapters.alibaba.dashscope.voice_enrollment import CUSTOMIZATION_PATH, CosyVoiceEnrollmentAdapter

POLICY = {"data": {"upload_host": "https://dashscope-file.oss.example.com", "upload_dir": "dashscope-instant/abc",
                   "policy": "p", "signature": "s", "oss_access_key_id": "k"}}


@pytest.fixture()
def bailian(monkeypatch):
    """记下发给百炼的每个请求(路径、查询参数、请求头、请求体),按 action 回事先写好的包。"""
    sent: list[dict[str, Any]] = []
    replies: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        sent.append({"path": request.url.path, "params": dict(request.url.params), "headers": request.headers, "json": body})
        if request.url.path == "/api/v1/uploads":
            return httpx.Response(200, json=POLICY)
        action = (body or {}).get("input", {}).get("action", "")
        return replies.get(action) or httpx.Response(200, json={"output": {}})

    real = voice_enrollment.RetryingClient

    def client(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(voice_enrollment, "RetryingClient", client)
    uploaded: list[dict[str, Any]] = []

    def fake_post(url, data=None, files=None, timeout=None):
        uploaded.append({"url": url, "data": data, "file": files["file"][0]})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(temporary_storage.httpx, "post", fake_post)
    return SimpleNamespace(sent=sent, replies=replies, uploaded=uploaded)


def _reference(tmp_path: Path) -> Path:
    path = tmp_path / "reference.wav"
    path.write_bytes(b"RIFFwav")
    return path


def test_建音色_先按voice_enrollment取凭证直传_再带oss解析头提交(bailian, tmp_path) -> None:
    bailian.replies["create_voice"] = httpx.Response(200, json={"output": {"voice_id": "cosyvoice-v3-flash-mabc123def-" + "0" * 32}})
    adapter = build_voice_enrollment_adapter("alibaba-cosyvoice", api_key="sk-test", base_url="")
    voice_id = adapter.create(target_model="cosyvoice-v3-flash", prefix="mabc123def", reference=_reference(tmp_path))

    assert voice_id.startswith("cosyvoice-v3-flash-mabc123def-")
    policy, create = bailian.sent
    assert policy["params"] == {"action": "getPolicy", "model": "voice-enrollment"}, "凭证只绑 voice-enrollment 这个模型"
    assert bailian.uploaded[0]["data"]["key"] == "dashscope-instant/abc/reference.wav"
    assert create["path"] == CUSTOMIZATION_PATH
    assert create["headers"]["x-dashscope-ossresourceresolve"] == "enable", "交 oss:// 地址要带这个头"
    assert create["headers"]["authorization"] == "Bearer sk-test"
    assert create["json"] == {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": "cosyvoice-v3-flash",
            "prefix": "mabc123def",
            "url": "oss://dashscope-instant/abc/reference.wav",
        },
    }


def test_对话那个兼容端点要剥成原生根(bailian, tmp_path) -> None:
    bailian.replies["create_voice"] = httpx.Response(200, json={"output": {"voice_id": "v"}})
    adapter = CosyVoiceEnrollmentAdapter(api_key="k", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    adapter.create(target_model="cosyvoice-v2", prefix="m123", reference=_reference(tmp_path))
    assert all(not one["path"].startswith("/compatible-mode") for one in bailian.sent)


@pytest.mark.parametrize("prefix", ["", "m12345678901", "m-abc"])
def test_前缀超过十个字符或带符号_不发请求(bailian, tmp_path, prefix: str) -> None:
    """百炼回「prefix should not be longer than 10 characters」;文档另说只收字母和数字。我们自己的前缀不该打过去换一个 400。"""
    with pytest.raises(ValueError):
        CosyVoiceEnrollmentAdapter(api_key="k").create(target_model="cosyvoice-v2", prefix=prefix, reference=_reference(tmp_path))
    assert bailian.sent == []


def test_建了却没给音色id_说出来(bailian, tmp_path) -> None:
    bailian.replies["create_voice"] = httpx.Response(200, json={"output": {}})
    with pytest.raises(VoiceEnrollmentError) as caught:
        CosyVoiceEnrollmentAdapter(api_key="k").create(target_model="cosyvoice-v2", prefix="m1", reference=_reference(tmp_path))
    assert caught.value.key == "providerErr_voiceEnrollNoVoiceId"


def test_报错照百炼原话(bailian, tmp_path) -> None:
    bailian.replies["create_voice"] = httpx.Response(
        400, json={"code": "InvalidParameter", "message": "prefix should not be longer than 10 characters"}
    )
    with pytest.raises(VoiceEnrollmentError) as caught:
        CosyVoiceEnrollmentAdapter(api_key="k").create(target_model="cosyvoice-v2", prefix="m1", reference=_reference(tmp_path))
    assert caught.value.params["detail"] == "HTTP 400 · InvalidParameter: prefix should not be longer than 10 characters"


@pytest.mark.parametrize(("raw", "status"), [("OK", "ok"), ("DEPLOYING", "deploying"), ("UNDEPLOYED", "failed")])
def test_查状态_百炼原词归一成三种(bailian, raw: str, status: str) -> None:
    bailian.replies["query_voice"] = httpx.Response(
        200, json={"output": {"status": raw, "target_model": "cosyvoice-v3-flash", "resource_link": "https://x"}}
    )
    found = CosyVoiceEnrollmentAdapter(api_key="k").query("cosyvoice-v3-flash-m1-abc")
    assert (found.status, found.raw_status, found.target_model) == (status, raw, "cosyvoice-v3-flash")
    assert bailian.sent[-1]["json"] == {"model": "voice-enrollment", "input": {"action": "query_voice", "voice_id": "cosyvoice-v3-flash-m1-abc"}}


def test_按前缀列_删(bailian) -> None:
    bailian.replies["list_voice"] = httpx.Response(200, json={"output": {"voice_list": [
        {"voice_id": "cosyvoice-v3-flash-m1-a", "status": "OK", "gmt_create": "2026-10-05 10:00:00"},
        {"voice_id": "cosyvoice-v2-m1-b", "status": "DEPLOYING"},
        {"status": "OK"},
    ]}})
    adapter = CosyVoiceEnrollmentAdapter(api_key="k")
    listed = adapter.list(prefix="m1")
    assert [(one.voice_id, one.status) for one in listed] == [("cosyvoice-v3-flash-m1-a", "ok"), ("cosyvoice-v2-m1-b", "deploying")]
    assert bailian.sent[-1]["json"]["input"] == {"action": "list_voice", "prefix": "m1", "page_index": 0, "page_size": 100}

    adapter.delete("cosyvoice-v2-m1-b")
    assert bailian.sent[-1]["json"] == {"model": "voice-enrollment", "input": {"action": "delete_voice", "voice_id": "cosyvoice-v2-m1-b"}}


def test_没有钥匙直接拒绝() -> None:
    with pytest.raises(VoiceEnrollmentError):
        CosyVoiceEnrollmentAdapter(api_key="")


def test_不收复刻的引擎说出来() -> None:
    with pytest.raises(VoiceEnrollmentError) as caught:
        build_voice_enrollment_adapter("edge", api_key="k")
    assert caught.value.key == "providerErr_voiceEnrollUnsupported"
