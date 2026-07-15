from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.ai.analysis import service
from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from tests.util import fresh_client

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def add_profile(client, vendor: str, name: str = "P") -> dict:
    return client.post(
        "/api/settings/providers",
        json={"name": name, "vendor": vendor, "api_key": f"sk-{vendor}"},
    ).json()


def test_profile_picking_prefers_vision_vendors() -> None:
    client = fresh_client()
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
