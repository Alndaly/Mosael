"""可灵数字人与对口型(ADR 0028 阶段 4)。

**不打网络**:钉住的是「照 2026-09-28 读到的官方文档把请求翻成了什么」—— 数字人一步提交,对口型先认人脸再对口型;
图片、音频传不带前缀的 Base64;对口型从出现最久的那张脸插入配音、截到两者短的那个、原声压到 0。
还没拿真实密钥跑到终态。
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from app.ai.providers.adapters.kuaishou.kling import avatar, connection, video
from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    SourceAsset,
)
from app.domain.generation.catalog import KLING_AVATAR_CAPABILITIES, KLING_LIPSYNC_CAPABILITIES


def _files(tmp_path: Path) -> tuple[Path, Path]:
    face = tmp_path / "face.png"
    face.write_bytes(b"\x89PNG fake")
    voice = tmp_path / "line.mp3"
    voice.write_bytes(b"ID3 fake mp3")
    return face, voice


def test_数字人请求体_不带前缀的_Base64_清晰度映射到模式(tmp_path) -> None:
    face, voice = _files(tmp_path)
    request = GenerationRequest(kind="video", model="kling-avatar", prompt="  边说边挥手 ",
                                parameters={"resolution": "1080p"},
                                sources=(SourceAsset(FIRST_FRAME, face), SourceAsset(DRIVING_AUDIO, voice)))
    body = avatar.build_avatar_payload(request)
    assert body["image"] == base64.b64encode(face.read_bytes()).decode() and not body["image"].startswith("data:")
    assert body["sound_file"] == base64.b64encode(voice.read_bytes()).decode()
    assert body["mode"] == "pro" and body["prompt"] == "边说边挥手"
    #: 给了链接就用链接。
    linked = GenerationRequest(kind="video", model="kling-avatar", prompt="",
                               parameters={"first_frame_url": "https://x/face.png", "driving_audio_url": "https://x/a.mp3"})
    linked_body = avatar.build_avatar_payload(linked)
    assert linked_body["image"] == "https://x/face.png" and linked_body["mode"] == "std" and "prompt" not in linked_body


def test_对口型_挑出现最久的脸_截到两者短的那个_原声压到零() -> None:
    faces = [{"face_id": "0", "start_time": 0, "end_time": 1500}, {"face_id": "1", "start_time": 1000, "end_time": 9000}]
    face = avatar.pick_face(faces)
    assert face["face_id"] == "1"
    body = avatar.build_lipsync_payload("s-1", face, "BASE64", audio_ms=5000)
    choice = body["face_choose"][0]
    assert body["session_id"] == "s-1" and choice["face_id"] == "1"
    assert (choice["sound_start_time"], choice["sound_end_time"], choice["sound_insert_time"]) == (0, 5000, 1000)
    assert choice["original_audio_volume"] == 0
    #: 配音比脸出现得还长:截到脸出现的那么长。
    assert avatar.build_lipsync_payload("s", face, "B", audio_ms=20000)["face_choose"][0]["sound_end_time"] == 8000
    with pytest.raises(GenerationAdapterError) as short:
        avatar.build_lipsync_payload("s", faces[0], "B", audio_ms=5000)
    assert short.value.key == "providerErr_klingFaceTooShort"
    with pytest.raises(GenerationAdapterError) as none:
        avatar.pick_face([])
    assert none.value.key == "providerErr_klingNoFace"


class _FakeKling:
    """记下每次请求;提交回任务号,查询回做完。"""

    last: "_FakeKling"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        _FakeKling.last = self

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _reply(self, payload: dict[str, Any]):
        class _Response:
            status_code = 200

            def json(self_inner) -> dict[str, Any]:
                return payload

            def raise_for_status(self_inner) -> None:
                return None

        return _Response()

    def post(self, path: str, json: dict[str, Any]):
        self.calls.append(("POST", path, json))
        if path == avatar.IDENTIFY_FACE_PATH:
            return self._reply({"code": 0, "data": {"session_id": "s-9", "face_data": [
                {"face_id": "7", "start_time": 500, "end_time": 6500}]}})
        return self._reply({"code": 0, "data": {"task_id": "t-1", "task_status": "submitted"}})

    def get(self, path: str):
        self.calls.append(("GET", path, None))
        return self._reply({"code": 0, "data": {"task_status": "succeed",
                                                "task_result": {"videos": [{"url": "https://cdn/out.mp4"}]}}})


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(connection, "RetryingClient", _FakeKling)
    downloaded: list[str] = []
    monkeypatch.setattr(video, "download_to_path", lambda url, target: downloaded.append(url) or str(target))
    return downloaded


def _context() -> GenerationAdapterContext:
    return GenerationAdapterContext(connection_id="c", vendor_id="kuaishou", api_key="AK", options={"secret_key": "SK"})


def test_数字人整条_提交到查询到下载(tmp_path, fake) -> None:
    face, voice = _files(tmp_path)
    request = GenerationRequest(kind="video", model="kling-avatar", prompt="",
                                sources=(SourceAsset(FIRST_FRAME, face), SourceAsset(DRIVING_AUDIO, voice)))
    result = video.KlingVideoAdapter().generate(request, _context(), tmp_path / "out")
    calls = _FakeKling.last.calls
    assert [(method, path) for method, path, _ in calls] == [("POST", avatar.AVATAR_PATH), ("GET", f"{avatar.AVATAR_PATH}/t-1")]
    assert fake == ["https://cdn/out.mp4"] and result.output_paths == [tmp_path / "out" / "generated.mp4"]


def test_对口型整条_先认人脸再对口型(tmp_path, fake, monkeypatch) -> None:
    _face, voice = _files(tmp_path)
    monkeypatch.setattr(avatar, "audio_duration_ms", lambda request: 4000)
    request = GenerationRequest(kind="video", model="kling-lipsync", prompt="",
                                parameters={"source_video_url": "https://x/clip.mp4"},
                                sources=(SourceAsset(DRIVING_AUDIO, voice),))
    video.KlingVideoAdapter().generate(request, _context(), tmp_path / "out")
    (m1, p1, identify), (m2, p2, lipsync), (m3, p3, _) = _FakeKling.last.calls
    assert (p1, identify) == (avatar.IDENTIFY_FACE_PATH, {"video_url": "https://x/clip.mp4"})
    assert p2 == avatar.LIPSYNC_PATH and lipsync["session_id"] == "s-9"
    assert lipsync["face_choose"][0] | {"sound_file": ""} == {
        "face_id": "7", "sound_file": "", "sound_start_time": 0, "sound_end_time": 4000, "sound_insert_time": 500,
        "sound_volume": 1, "original_audio_volume": 0}
    assert (m3, p3) == ("GET", f"{avatar.LIPSYNC_PATH}/t-1")


def test_描述符_数字人不用直链_对口型的原片只收链接() -> None:
    assert KLING_AVATAR_CAPABILITIES["modes"] == ["speech-to-video"] and "url_only_roles" not in KLING_AVATAR_CAPABILITIES
    assert KLING_AVATAR_CAPABILITIES["source_duration_seconds"] == {"driving_audio": [2, 300]}
    assert KLING_LIPSYNC_CAPABILITIES["modes"] == ["video-lipsync"]
    assert KLING_LIPSYNC_CAPABILITIES["url_only_roles"] == ["source_video"]
    assert KLING_LIPSYNC_CAPABILITIES["duration_follows"] == "source_video"
