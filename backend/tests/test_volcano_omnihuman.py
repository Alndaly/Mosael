"""火山 · 即梦 OmniHuman 1.5 说话照片(ADR 0028 阶段 4)。

**不打网络**:风险在「把内部请求翻成即梦的形状」「签名打到对的服务和地域」「从回包里捞地址、认错误码」。接口形状照
2026-09-28 读到的官方文档写,还没拿真实密钥跑到终态 —— 这里钉住的是我们照文档写成了什么。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.providers.adapters.bytedance.volcano import omnihuman
from app.ai.providers.adapters.bytedance.volcano.omnihuman import (
    VolcanoOmniHumanAdapter,
    build_body,
    extract_video,
)
from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationAdapterError, GenerationRequest
from app.domain.generation.catalog import VOLCANO_OMNIHUMAN_15_CAPABILITIES


def _request(**parameters: Any) -> GenerationRequest:
    base = {"first_frame_url": "https://cdn.example.com/face.png", "driving_audio_url": "https://cdn.example.com/line.mp3"}
    return GenerationRequest(kind="video", model="omnihuman-1.5", prompt="", parameters={**base, **parameters})


def test_请求体照文档_分辨率带着快速模式() -> None:
    body = build_body(_request(resolution="720p", seed=7))
    assert body == {"req_key": "jimeng_realman_avatar_picture_omni_v15", "image_url": "https://cdn.example.com/face.png",
                    "audio_url": "https://cdn.example.com/line.mp3", "seed": 7, "output_resolution": 720, "pe_fast_mode": True}
    assert build_body(_request(resolution="1080p"))["pe_fast_mode"] is False, "文档建议:1080 关快速模式"
    with_prompt = GenerationRequest(kind="video", model="omnihuman-1.5", prompt=" 挥手打招呼 ",
                                    parameters=_request().parameters)
    assert build_body(with_prompt)["prompt"] == "挥手打招呼"


def test_没有公网链接就说缺哪一样() -> None:
    request = GenerationRequest(kind="video", model="omnihuman-1.5", prompt="",
                                parameters={"first_frame_url": "https://cdn.example.com/face.png"})
    with pytest.raises(GenerationAdapterError) as missing:
        build_body(request)
    assert missing.value.key == "providerErr_sourceMissing"


def test_查询回包_先看外层码再看状态() -> None:
    done = {"code": 10000, "data": {"status": "done", "video_url": "https://x/v.mp4", "aigc_meta_tagged": False}}
    assert extract_video(done)["video_url"] == "https://x/v.mp4"
    assert extract_video({"code": 10000, "data": {"status": "generating"}}) is None
    with pytest.raises(GenerationAdapterError) as blocked:
        extract_video({"code": 50411, "data": None, "message": "Pre Img Risk Not Pass"})
    assert "50411" in str(blocked.value)
    with pytest.raises(GenerationAdapterError):
        extract_video({"code": 10000, "data": {"status": "expired"}})


class _FakeHttp:
    """记下每次 POST;提交回任务号,查询回做完。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.base_url = kwargs.get("base_url")
        self.posts: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        _FakeHttp.last = self

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def post(self, path: str, headers: dict[str, str], content: bytes):
        body = json.loads(content)
        self.posts.append((path, headers, body))
        reply = ({"code": 10000, "data": {"task_id": "t-1"}} if "CVSubmitTask" in path
                 else {"code": 10000, "data": {"status": "done", "video_url": "https://x/v.mp4"}})

        class _Response:
            status_code = 200

            def json(self) -> dict[str, Any]:
                return reply

            def raise_for_status(self) -> None:
                return None

        return _Response()


def test_整条提交到下载_签名打到即梦的服务和地域(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(omnihuman, "RetryingClient", _FakeHttp)
    monkeypatch.setattr(omnihuman, "POLL_INTERVAL_SECONDS", 0)
    downloaded: list[tuple[str, Path]] = []
    monkeypatch.setattr(omnihuman, "download_to_path", lambda url, target: downloaded.append((url, target)) or str(target))
    context = GenerationAdapterContext(connection_id="c", vendor_id="volcano-visual", api_key="AK", options={"sk": "SK"})
    result = VolcanoOmniHumanAdapter().generate(_request(), context, tmp_path)
    http = _FakeHttp.last
    assert http.base_url == "https://visual.volcengineapi.com"
    (submit_path, headers, submitted), (query_path, _, queried) = http.posts
    assert submit_path == "/?Action=CVSubmitTask&Version=2022-08-31" and query_path == "/?Action=CVGetResult&Version=2022-08-31"
    assert "/cn-north-1/cv/request" in headers["Authorization"] and headers["Host"] == "visual.volcengineapi.com"
    assert "SK" not in headers["Authorization"], "SK 只用来签名,不出现在请求里"
    assert queried == {"req_key": "jimeng_realman_avatar_picture_omni_v15", "task_id": "t-1"}
    assert submitted["image_url"] == "https://cdn.example.com/face.png"
    assert downloaded == [("https://x/v.mp4", tmp_path / "generated.mp4")] and result.output_paths == [tmp_path / "generated.mp4"]


def test_没有_AK_SK_当场说() -> None:
    context = GenerationAdapterContext(connection_id="c", vendor_id="volcano-visual", api_key="AK", options={})
    with pytest.raises(GenerationAdapterError) as refused:
        VolcanoOmniHumanAdapter().generate(_request(), context, Path("/tmp"))
    assert refused.value.key == "providerErr_volcanoVisualKeysMissing"


def test_描述符_说话照片_素材只收链接_音频短于一分钟() -> None:
    caps = VOLCANO_OMNIHUMAN_15_CAPABILITIES
    assert caps["modes"] == ["speech-to-video"] and caps["duration_follows"] == "driving_audio"
    assert set(caps["url_only_roles"]) == {"first_frame", "driving_audio"}
    assert caps["source_duration_seconds"]["driving_audio"][1] < 60
