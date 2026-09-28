"""海外数字人 HeyGen / Hedra(ADR 0028 阶段 4)。

**不打网络**:钉住的是「照 2026-09-28 读到的官方文档把请求翻成了什么」——
HeyGen 说话照片内联 Base64 人像、配音走直传(预签名 PUT 不带 Key)、对口型用精度模式;
Hedra 图和配音都先传到它自己的 /files(外链它不认)、提示词必填、画幅按原图挑。还没拿真实密钥跑到终态。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.providers.adapters.hedra import video as hedra
from app.ai.providers.adapters.heygen import video as heygen
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    SOURCE_VIDEO,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    SourceAsset,
)
from app.domain.generation.catalog import (
    HEDRA_CHARACTER_3_CAPABILITIES,
    HEYGEN_AVATAR_CAPABILITIES,
    HEYGEN_LIPSYNC_CAPABILITIES,
)


class _Reply:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """记下每次请求;按路径回话。"""

    last: "_FakeClient"
    routes: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.headers = kwargs.get("headers") or {}
        self.calls: list[tuple[str, str, Any]] = []
        _FakeClient.last = self

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _answer(self, method: str, path: str, body: Any) -> _Reply:
        self.calls.append((method, path, body))
        for prefix, reply in self.routes.items():
            if path.startswith(prefix):
                return _Reply(reply(body) if callable(reply) else reply)
        raise AssertionError(f"{method} {path}")

    def post(self, path: str, json: Any = None, files: Any = None):
        return self._answer("POST", path, json if files is None else files)

    def get(self, path: str):
        return self._answer("GET", path, None)


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    face = tmp_path / "face.png"
    face.write_bytes(b"\x89PNG fake")
    voice = tmp_path / "line.mp3"
    voice.write_bytes(b"ID3 fake mp3")
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake mp4")
    return face, voice, clip


@pytest.fixture
def fake(monkeypatch):
    downloaded: list[str] = []
    puts: list[tuple[str, bytes, dict]] = []
    for module in (heygen, hedra):
        monkeypatch.setattr(module, "RetryingClient", _FakeClient)
        monkeypatch.setattr(module, "download_to_path", lambda url, target: downloaded.append(url) or "video/mp4")
        monkeypatch.setattr(module, "POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(heygen, "put_to_presigned_url", lambda url, data, headers: puts.append((url, data, headers)))
    return {"downloaded": downloaded, "puts": puts}


def _context(vendor: str) -> GenerationAdapterContext:
    return GenerationAdapterContext(connection_id="c", vendor_id=vendor, api_key="KEY")


_UPLOADS = {
    "/v3/assets/direct-uploads": {"data": {"asset_id": "as-1", "upload_url": "https://s3/put?sig=1",
                                           "upload_headers": {"x-amz-meta": "m"}}},
    "/v3/assets/as-1/complete": {"data": {"asset_id": "as-1", "status": "processing"}},
}


def test_HeyGen_说话照片_人像内联_配音直传_查到完成就下(tmp_path, fake) -> None:
    face, voice, _ = _files(tmp_path)
    _FakeClient.routes = {
        **_UPLOADS,
        "/v3/videos/v-1": {"data": {"status": "completed", "video_url": "https://cdn/out.mp4", "duration": 3.2}},
        "/v3/videos": {"data": {"video_id": "v-1", "status": "waiting"}},
    }
    request = GenerationRequest(kind="video", model="heygen-avatar-iv", prompt=" 边说边点头 ",
                                parameters={"resolution": "1080p"},
                                sources=(SourceAsset(FIRST_FRAME, face), SourceAsset(DRIVING_AUDIO, voice)))
    heygen.HeyGenVideoAdapter().generate(request, _context("heygen"), tmp_path / "out")
    client = _FakeClient.last
    assert client.headers == {"X-Api-Key": "KEY"}
    submitted = next(body for method, path, body in client.calls if path == "/v3/videos")
    assert submitted["image"] == {"type": "base64", "media_type": "image/png",
                                  "data": base64.b64encode(face.read_bytes()).decode()}
    assert submitted["audio_asset_id"] == "as-1" and "audio_url" not in submitted
    assert (submitted["type"], submitted["aspect_ratio"], submitted["resolution"], submitted["motion_prompt"]) == (
        "image", "auto", "1080p", "边说边点头")
    slot = next(body for method, path, body in client.calls if path == "/v3/assets/direct-uploads")
    assert slot == {"filename": "line.mp3", "content_type": "audio/mpeg", "size_bytes": voice.stat().st_size}
    #: 字节 PUT 到预签名地址,带着对面要求的头;Key 不跟着去对象存储。
    assert fake["puts"] == [("https://s3/put?sig=1", voice.read_bytes(), {"x-amz-meta": "m"})]
    assert fake["downloaded"] == ["https://cdn/out.mp4"]


def test_HeyGen_对口型_给了链接就用链接_精度模式(tmp_path, fake) -> None:
    _, voice, _ = _files(tmp_path)
    _FakeClient.routes = {
        **_UPLOADS,
        "/v3/lipsyncs/l-1": {"data": {"status": "completed", "video_url": "https://cdn/lip.mp4"}},
        "/v3/lipsyncs": {"data": {"lipsync_id": "l-1"}},
    }
    request = GenerationRequest(kind="video", model="heygen-lipsync", prompt="",
                                parameters={"source_video_url": "https://x/clip.mp4"},
                                sources=(SourceAsset(DRIVING_AUDIO, voice),))
    heygen.HeyGenVideoAdapter().generate(request, _context("heygen"), tmp_path / "out")
    submitted = next(body for method, path, body in _FakeClient.last.calls if path == "/v3/lipsyncs")
    assert submitted == {"video": {"type": "url", "url": "https://x/clip.mp4"},
                         "audio": {"type": "asset_id", "asset_id": "as-1"}, "mode": "precision"}
    assert [path for method, path, _ in _FakeClient.last.calls if method == "GET"] == ["/v3/lipsyncs/l-1"]


def test_HeyGen_失败按错误码归类_原片格式不对提前说(tmp_path) -> None:
    with pytest.raises(GenerationAdapterError) as failed:
        heygen.extract_video({"data": {"status": "failed", "failure_code": "insufficient_credit", "failure_message": "no credit"}})
    assert failed.value.key == "providerErr_upstreamBalance"
    assert heygen.extract_video({"data": {"status": "processing"}}) is None
    mov = tmp_path / "clip.mkv"
    mov.write_bytes(b"x")
    with pytest.raises(GenerationAdapterError) as unsupported:
        heygen.uploadable(mov, SOURCE_VIDEO, tmp_path)
    assert unsupported.value.key == "providerErr_heygenVideoFormat"


def test_Hedra_图和配音先传_提示词必填_画幅按原图挑(tmp_path, fake, monkeypatch) -> None:
    face, voice, _ = _files(tmp_path)
    monkeypatch.setattr(hedra, "_image_size", lambda path: (1080, 1920))
    uploaded: list[str] = []

    def upload(files):
        name = files["file"][0]
        uploaded.append(name)
        return {"url": f"https://hedra-files/{name}?sig=1", "content_type": "x", "expires_at": "later"}

    _FakeClient.routes = {
        "/files": upload,
        "/models/hedra-character-3": {"job_id": "j-1", "status": "IN_QUEUE"},
        "/jobs/j-1": {"job_id": "j-1", "status": "COMPLETED", "outputs": [{"url": "https://cdn/h.mp4"}]},
    }
    request = GenerationRequest(kind="video", model="hedra-character-3", prompt="",
                                sources=(SourceAsset(FIRST_FRAME, face), SourceAsset(DRIVING_AUDIO, voice)))
    hedra.HedraVideoAdapter().generate(request, _context("hedra"), tmp_path / "out")
    client = _FakeClient.last
    assert client.headers == {"Authorization": "Key KEY"}
    assert uploaded == ["face.png", "line.mp3"]
    body = next(body for method, path, body in client.calls if path == "/models/hedra-character-3")["input"]
    assert body == {
        "prompt": hedra.DEFAULT_PROMPT, "aspect_ratio": "9:16", "resolution": "720p",
        "start_image": {"source": "url", "url": "https://hedra-files/face.png?sig=1"},
        "audio": {"source": "url", "url": "https://hedra-files/line.mp3?sig=1"},
    }
    assert fake["downloaded"] == ["https://cdn/h.mp4"]


def test_Hedra_画幅_失败归类() -> None:
    assert hedra.closest_aspect_ratio(1920, 1080) == "16:9"
    assert hedra.closest_aspect_ratio(1000, 1000) == "1:1"
    assert hedra.closest_aspect_ratio(900, 1200) == "3:4"
    assert hedra.closest_aspect_ratio(None, None) == "1:1"
    with pytest.raises(GenerationAdapterError) as failed:
        hedra.extract_video({"status": "FAILED", "error": {"code": "MODERATION_FAILED", "message": "no"}})
    assert failed.value.key == "providerErr_upstreamContentBlocked"
    assert hedra.extract_video({"status": "IN_PROGRESS"}) is None


def test_描述符_都不要对象存储_按模式进数字人节点() -> None:
    for descriptor in (HEYGEN_AVATAR_CAPABILITIES, HEYGEN_LIPSYNC_CAPABILITIES, HEDRA_CHARACTER_3_CAPABILITIES):
        assert "url_only_roles" not in descriptor, "两家都有自己的上传,不该要用户先配对象存储"
    assert HEYGEN_AVATAR_CAPABILITIES["modes"] == HEDRA_CHARACTER_3_CAPABILITIES["modes"] == ["speech-to-video"]
    assert HEYGEN_LIPSYNC_CAPABILITIES["modes"] == ["video-lipsync"]
    assert HEDRA_CHARACTER_3_CAPABILITIES["source_duration_seconds"] == {"driving_audio": [1, 600]}
