from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.ai.analysis import service
from app.core.db import SessionLocal
from app.db.models import Asset, ProviderProfile
from tests.util import make_video_asset
from tests.util import fresh_client

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def add_profile(client, vendor: str, name: str = "P") -> dict:
    return client.post(
        "/api/settings/providers",
        json={"name": name, "vendor": vendor, "config": {"api_key": f"sk-{vendor}"}},
    ).json()


def test_profile_picking_prefers_vision_vendors() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})  # instance settings need an admin
    with SessionLocal() as db:
        with pytest.raises(service.AnalysisError):
            service.pick_analysis_profile(db)
    add_profile(client, "minimax")
    add_profile(client, "moonshot")
    with SessionLocal() as db:
        assert service.pick_analysis_profile(db).vendor == "moonshot"  # order: moonshot first


def test_build_messages_shape() -> None:
    class FakeAsset:
        name = "海边素材"
        kind = "video"
        media_info = {"duration": 8.0}

    messages = service.build_messages(FakeAsset(), "画面里有什么？", [b"a", b"b"])
    content = messages[0]["content"]
    assert content[0]["type"] == "text"
    assert "海边素材" in content[0]["text"] and "2 帧" in content[0]["text"]
    assert [part["type"] for part in content[1:]] == ["image_url", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_build_messages_includes_transcript() -> None:
    class FakeAsset:
        name = "对谈"
        kind = "video"
        media_info = {"duration": 30.0}

    messages = service.build_messages(FakeAsset(), "讲了什么？", [b"a"], transcript="你好，今天聊剪辑。")
    text = messages[0]["content"][0]["text"]
    assert "语音转写" in text
    assert "你好，今天聊剪辑。" in text


def test_adaptive_frame_count_scales_with_duration() -> None:
    # 约每 6 秒 1 帧,夹在 [4, 16]。
    assert service.adaptive_frame_count(0) == service.MIN_VIDEO_FRAMES
    assert service.adaptive_frame_count(3) == service.MIN_VIDEO_FRAMES  # 太短也保底 4 帧
    assert service.adaptive_frame_count(60) == 10
    assert service.adaptive_frame_count(6000) == service.MAX_VIDEO_FRAMES  # 长视频封顶


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_extract_video_frames(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, timeout=60,
    )
    frames = service.extract_video_frames(video, count=4)
    assert 1 <= len(frames) <= 4
    assert all(frame[:2] == b"\xff\xd8" for frame in frames)  # JPEG magic


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_analyze_endpoint_end_to_end(monkeypatch, tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    add_profile(client, "moonshot", "Kimi")

    image = tmp_path / "pic.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=64x64", "-frames:v", "1", str(image)],
        check=True, timeout=30,
    )
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("pic.jpg", image.read_bytes(), "image/jpeg")},
    ).json()

    captured: dict = {}

    def fake_call(profile: ProviderProfile, messages):
        captured["model_profile"] = profile.vendor
        captured["parts"] = len(messages[0]["content"])
        return "画面是一张纯红色图片。"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    res = client.post(f"/api/assets/{asset['id']}/analyze", json={"question": "这是什么颜色？"})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["answer"] == "画面是一张纯红色图片。"
    assert payload["provider"] == "moonshot"
    assert captured["parts"] == 2  # text + one image


def test_analyze_rejects_audio_assets() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    add_profile(client, "moonshot")
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "audio", "name": "song", "file_key": "media/s.mp3", "media_info": {}},
    ).json()
    res = client.post(f"/api/assets/{asset['id']}/analyze", json={"question": "?"})
    assert res.status_code == 422


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _add_native_profile(db, vendor: str, base_url: str = "", model: str = "m") -> None:
    db.add(ProviderProfile(name=vendor, vendor=vendor, base_url=base_url, api_key=f"sk-{vendor}", default_model=model))
    db.commit()


def test_pick_native_video_profile_priority() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        assert service.pick_native_video_profile(db) is None
        _add_native_profile(db, "moonshot")
        _add_native_profile(db, "alibaba")
    with SessionLocal() as db:
        assert service.pick_native_video_profile(db).vendor == "alibaba"  # google>alibaba>moonshot
        _add_native_profile(db, "google", base_url="https://gl/v1beta", model="gemini-2.0-flash")
    with SessionLocal() as db:
        assert service.pick_native_video_profile(db).vendor == "google"


def test_analyze_video_native_qwen_video_url(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResp({"choices": [{"message": {"content": "海边散步的女孩"}}]})

    monkeypatch.setattr(service.httpx, "post", fake_post)
    with SessionLocal() as db:
        _add_native_profile(db, "alibaba", base_url="https://dashscope/compatible-mode/v1", model="qwen-vl-max")
        asset = db.get(Asset, asset_json["id"])
        result = service.analyze_asset(db, asset, "讲了什么", mode="native")
    assert result["mode"] == "native" and result["provider"] == "alibaba"
    assert result["answer"] == "海边散步的女孩"
    content = captured["json"]["messages"][0]["content"]
    assert any(part.get("type") == "video_url" for part in content)
    assert content[-1]["video_url"]["url"].startswith("data:video/mp4;base64,")


def test_analyze_video_native_gemini_inline_data(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["params"] = kwargs.get("params")
        return _FakeResp({"candidates": [{"content": {"parts": [{"text": "Gemini 看到了海"}]}}]})

    monkeypatch.setattr(service.httpx, "post", fake_post)
    with SessionLocal() as db:
        _add_native_profile(db, "google", base_url="https://generativelanguage.googleapis.com/v1beta", model="gemini-2.0-flash")
        asset = db.get(Asset, asset_json["id"])
        result = service.analyze_asset(db, asset, "描述", mode="native")
    assert result["mode"] == "native" and result["provider"] == "google"
    assert ":generateContent" in captured["url"]
    assert captured["params"]["key"] == "sk-google"
    parts = captured["json"]["contents"][0]["parts"]
    assert parts[1]["inline_data"]["mime_type"] == "video/mp4"


def test_analyze_native_without_provider_errors() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    with SessionLocal() as db:
        asset = db.get(Asset, asset_json["id"])
        with pytest.raises(service.AnalysisError):
            service.analyze_asset(db, asset, "?", mode="native")


def test_analyze_auto_falls_back_to_frames(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    monkeypatch.setattr(service, "extract_video_frames", lambda path: [b"f1", b"f2"])
    monkeypatch.setattr(service, "call_vision_model", lambda profile, messages: "抽帧描述")
    with SessionLocal() as db:
        _add_native_profile(db, "minimax")  # 视觉但非原生视频
        asset = db.get(Asset, asset_json["id"])
        result = service.analyze_asset(db, asset, "?", mode="auto")
    assert result["mode"] == "frames" and result["frames"] == 2


def test_native_video_size_guard(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset_json = make_video_asset(client, ws["id"])
    monkeypatch.setattr(service, "MAX_NATIVE_VIDEO_MB", 0)  # 任何视频都超限
    with SessionLocal() as db:
        _add_native_profile(db, "alibaba")
        asset = db.get(Asset, asset_json["id"])
        with pytest.raises(service.AnalysisError):
            service.analyze_asset(db, asset, "?", mode="native")
