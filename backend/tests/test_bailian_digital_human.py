"""阿里云百炼的数字人适配器(ADR 0028 §3):`wan2.2-s2v` 说话照片、`videoretalk` 改口型。

**不打网络**,和 test_bailian_video 同一套理由:风险全在「把内部请求翻成百炼的形状」和「从回包里捞地址」。
接口形状照 2026-09-26 的官方文档,还没拿真实密钥跑到终态 —— 这里钉住的是我们照文档写成了什么。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.providers.adapters.alibaba.dashscope import uploads as temporary_storage
from app.ai.providers.adapters.alibaba.dashscope.digital_human import (
    DETECT_PATH,
    SUBMIT_PATH,
    build_talking_payload,
    is_talking_model,
    submit_talking,
)
from app.ai.providers.adapters.alibaba.dashscope.video import extract_video_url
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    SOURCE_VIDEO,
    GenerationAdapterError,
    GenerationRequest,
    SourceAsset,
)
from tests.util import stub_client


class FakeClient:
    """记下发出去的每一个请求;按路径回事先写好的包。"""

    def __init__(self, replies: dict[str, dict[str, Any]]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _reply(self, path: str) -> Any:
        body = self.replies[path]
        return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None)

    def get(self, path: str, params: dict[str, Any] | None = None, **_kw):
        self.calls.append(("GET", path, {"params": params}))
        return self._reply(path)

    def post(self, path: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, **_kw):
        self.calls.append(("POST", path, {"json": json, "headers": headers or {}}))
        return self._reply(path)

    def build_request(self, method: str, path: str, json: dict[str, Any] | None = None,
                      headers: dict[str, str] | None = None, **_kw):
        return SimpleNamespace(method=method, path=path, json=json, headers=dict(headers or {}))

    def send(self, request, **_kw):
        self.calls.append((request.method, request.path, {"json": request.json, "headers": request.headers}))
        return self._reply(request.path)


POLICY = {"data": {"upload_host": "https://dashscope-file.oss.example.com", "upload_dir": "dashscope-instant/abc",
                   "policy": "p", "signature": "s", "oss_access_key_id": "k", "x_oss_object_acl": "private",
                   "x_oss_forbid_overwrite": "true"}}


@pytest.fixture()
def uploads(monkeypatch):
    """直传 OSS 那一步(不带 Authorization 的表单 POST)换成假的,记下传了什么。"""
    sent: list[dict[str, Any]] = []

    def fake_post(url, data=None, files=None, timeout=None):
        sent.append({"url": url, "data": data, "file": files["file"][0]})
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(temporary_storage, "RetryingClient", stub_client(post=fake_post))
    return sent


def _request(model: str, sources: list[tuple[str, Path | None, str | None]], parameters: dict | None = None) -> GenerationRequest:
    return GenerationRequest(
        kind="video", model=model, prompt="", parameters=parameters or {},
        sources=tuple(SourceAsset(role=role, path=path or Path("/nonexistent"), public_url=url) for role, path, url in sources),
    )


def test_认得哪两个模型走这条路() -> None:
    assert is_talking_model("wan2.2-s2v") and is_talking_model("videoretalk")
    assert not is_talking_model("wan2.2-s2v-detect") and not is_talking_model("wan2.7-i2v")


def test_说话照片_本地素材先传百炼临时存储_预检通过再提交_带上_oss_解析头(tmp_path, uploads) -> None:
    face, voice = tmp_path / "face.png", tmp_path / "line.mp3"
    face.write_bytes(b"png")
    voice.write_bytes(b"mp3")
    client = FakeClient({
        "/api/v1/uploads": POLICY,
        DETECT_PATH: {"output": {"check_pass": True, "humanoid": True}},
        SUBMIT_PATH: {"output": {"task_id": "t-1", "task_status": "PENDING"}},
    })
    task = submit_talking(client, _request("wan2.2-s2v", [(FIRST_FRAME, face, None), (DRIVING_AUDIO, voice, None)],
                                            {"resolution": "720p"}))
    assert task == "t-1"
    assert [one["file"] for one in uploads] == ["line.mp3", "face.png"]
    assert uploads[0]["data"]["key"] == "dashscope-instant/abc/line.mp3"
    assert list(uploads[0]["data"])[-1] == "success_action_status", "表单字段照文档的顺序,file 另外放在最后"
    detect = next(call for call in client.calls if call[1] == DETECT_PATH)
    assert detect[2]["json"] == {"model": "wan2.2-s2v-detect", "input": {"image_url": "oss://dashscope-instant/abc/face.png"}}
    submit = client.calls[-1]
    assert submit[1] == SUBMIT_PATH and submit[2]["headers"] == {"X-DashScope-OssResourceResolve": "enable"}
    assert submit[2]["json"] == {
        "model": "wan2.2-s2v",
        "input": {"image_url": "oss://dashscope-instant/abc/face.png", "audio_url": "oss://dashscope-instant/abc/line.mp3"},
        "parameters": {"resolution": "720P"},
    }
    policy = next(call for call in client.calls if call[1] == "/api/v1/uploads")
    assert policy[2]["params"] == {"action": "getPolicy", "model": "wan2.2-s2v"}, "临时文件只绑这一个模型"


def test_预检不过_不提交_说没找到清晰的正脸(tmp_path, uploads) -> None:
    client = FakeClient({
        "/api/v1/uploads": POLICY,
        DETECT_PATH: {"output": {"check_pass": False, "code": "", "message": "no face"}},
    })
    with pytest.raises(GenerationAdapterError) as caught:
        build_talking_payload(client, _request("wan2.2-s2v", [(FIRST_FRAME, None, "https://x/face.png"),
                                                               (DRIVING_AUDIO, None, "https://x/a.mp3")]))
    assert caught.value.key == "providerErr_noUsableFace"
    assert all(call[1] != SUBMIT_PATH for call in client.calls)
    assert uploads == [], "有公网直链的素材直接用直链,不再上传"


def test_改口型_视频加音频_音频长了就把视频补齐() -> None:
    client = FakeClient({})
    payload = build_talking_payload(client, _request("videoretalk", [(SOURCE_VIDEO, None, "https://x/v.mp4"),
                                                                     (DRIVING_AUDIO, None, "https://x/a.mp3")]))
    assert payload == {"model": "videoretalk", "input": {"video_url": "https://x/v.mp4", "audio_url": "https://x/a.mp3"},
                       "parameters": {"video_extension": True}}
    assert client.calls == [], "改口型没有预检"


def test_说话照片的结果是一个对象_不是数组() -> None:
    reply = {"output": {"task_status": "SUCCEEDED", "results": {"video_url": "https://oss/result.mp4"}}}
    assert extract_video_url(reply) == "https://oss/result.mp4"


def test_两个模型在目录里_成片时长跟着音频_不收提示词() -> None:
    from app.domain.generation.catalog import VIDEORETALK_CAPABILITIES, WAN_22_S2V_CAPABILITIES

    for caps in (WAN_22_S2V_CAPABILITIES, VIDEORETALK_CAPABILITIES):
        assert caps["duration_follows"] == "driving_audio" and caps["prompt"] == "none"
        assert "duration_seconds" not in caps["parameter_keys"], "时长跟着音频走的模型不收时长"
    assert WAN_22_S2V_CAPABILITIES["modes"] == ["speech-to-video"]
    assert VIDEORETALK_CAPABILITIES["modes"] == ["video-lipsync"]


def test_人脸预检是同步接口_不带异步头() -> None:
    """真跑「稿子 → 数字人口播」:预检(face-detect)跟着提交任务的客户端带上了 `X-DashScope-Async: enable`,
    百炼回 403「current user api does not support asynchronous calls」,一次都没走到提交。预检是同步接口。"""
    import httpx

    from app.ai.providers.adapters.alibaba.dashscope.digital_human import check_portrait
    from app.core.http_retry import RetryingClient

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"output": {"check_pass": True, "humanoid": True}})

    client = RetryingClient(base_url="https://dashscope.example.com",
                            headers={"Authorization": "Bearer k", "X-DashScope-Async": "enable"},
                            transport=httpx.MockTransport(handler))
    check_portrait(client, "oss://dashscope-instant/abc/face.png")
    assert len(seen) == 1 and seen[0].url.path == DETECT_PATH
    assert "x-dashscope-async" not in seen[0].headers, dict(seen[0].headers)
    assert seen[0].headers["x-dashscope-ossresourceresolve"] == "enable", "oss:// 的临时地址照样要解析"
    assert seen[0].headers["authorization"] == "Bearer k"


def test_改口型的原视频不在_640_到_2048_之间_先缩放进范围再传(tmp_path, monkeypatch) -> None:
    """真跑:说话照片交回的视频是 512×512,交给改口型被百炼拒「The height or width of video must be 640 ~ 2048」。"""
    import subprocess

    from app.core.config import settings

    source = tmp_path / "talk.mp4"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=512x512:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
    sizes: list[str] = []

    def fake_post(url, data=None, files=None, timeout=None):
        name, handle = files["file"]
        kept = tmp_path / f"uploaded-{name}"
        kept.write_bytes(handle.read())
        probe = subprocess.run([settings.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", str(kept)],
                               capture_output=True, text=True, encoding="utf-8")
        sizes.append(probe.stdout.strip())
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(temporary_storage, "RetryingClient", stub_client(post=fake_post))
    client = FakeClient({"/api/v1/uploads": POLICY})
    payload = build_talking_payload(client, _request("videoretalk", [(SOURCE_VIDEO, source, None),
                                                                     (DRIVING_AUDIO, None, "https://x/a.mp3")]))
    assert sizes == ["640,640"], sizes
    assert payload["input"]["video_url"].startswith("oss://")
