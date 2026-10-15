"""analyze_asset 换喂法(ADR 0061 §3):抽帧路按镜头抽、每张图标镜号;两条路都带上已有镜头表。

视觉调用打桩(monkeypatch service.call_vision_model),收提示词与帧;视频用 ffmpeg 现造的四刀口小片子。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, ShotBreakdown
from app.domain.analysis import service
from tests.util import fresh_client, insert_asset

HAS_FFMPEG = shutil.which("ffmpeg") is not None
pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _make_cut_video(target: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=white:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=yellow:s=320x180:r=25:d=1",
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(target)],
        check=True, timeout=60,
    )


@pytest.fixture
def client():
    return fresh_client()


@pytest.fixture
def video_asset(client):
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = settings.media_dir / "test-shots-analysis"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"cuts-{uuid4().hex[:8]}.mp4"
    _make_cut_video(source)
    asset_id = insert_asset(
        ws_id, kind="video", name="刀口样片",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": 4.0, "width": 320, "height": 180, "fps": 25},
    )
    with SessionLocal() as db:
        yield db.get(Asset, asset_id)
    shutil.rmtree(media / "test-shots-analysis", ignore_errors=True)


def _add_vision_profile(client) -> None:
    client.post("/api/settings/providers", json={"name": "Kimi", "vendor": "moonshot",
                                                 "config": {"api_key": "sk-moonshot"}})


def _captured_analyze(client, monkeypatch, asset_id: str, question: str = "这条片子的节奏怎么样?") -> dict:
    from app.db.models import User

    captured: dict = {}

    def fake_call(db, profile, messages, call=None, **kwargs):
        captured["messages"] = messages
        return "看完了"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    response = client.post(f"/api/assets/{asset_id}/analyze", json={"question": question, "mode": "frames"})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first().id
        result = service.analyze_asset(db, db.get(Asset, asset_id), question,
                                       mode="frames", user_id=me)
    captured["result"] = result
    return captured


def _content_text(messages: list) -> tuple[str, list[str]]:
    parts = messages[0]["content"]
    text = next(p["text"] for p in parts if p["type"] == "text")
    labels = [p["text"] for p in parts if p["type"] == "text" and p["text"].startswith("【S")]
    return text, labels


def test_frames_path_samples_per_shot_with_labels(client, video_asset, monkeypatch) -> None:
    """没拆过镜头:现场量刀口(只量刀口那一路),每镜一帧取中点,每张图前标 S0X · 起–止。"""
    _add_vision_profile(client)
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    text, labels = _content_text(captured["messages"])
    assert "按镜头抽取的" in text
    assert "【S01 · 0:00.0–0:01.0】" in labels
    assert "【S04 · 0:03.0–0:04.0】" in labels
    assert len(labels) == 4  # 4 镜 ≤ 16 帧上限,每镜一帧
    parts = captured["messages"][0]["content"]
    images = [p for p in parts if p["type"] == "image_url"]
    assert len(images) == 4
    assert captured["result"]["frames"] == 4


def test_frames_path_uses_existing_breakdown_and_sends_shot_table(client, video_asset, monkeypatch) -> None:
    """拆过镜头:直接用表里的刀口(不再量一遍),提示词带上判过的景别运镜。"""
    _add_vision_profile(client)
    with SessionLocal() as db:
        db.add(ShotBreakdown(
            asset_id=video_asset.id, workspace_id=video_asset.workspace_id, lang="zh",
            params={}, meta={"duration": 4.0},
            cuts=[{"time": 2.0, "score": 0.9}],
            shots=[{"id": "S01", "start": 0.0, "end": 2.0, "seconds": 2.0, "motion": 0.1,
                    "size": "wide", "camera": ["static"], "dialogue": "开场", "frame": "海边的全景"},
                   {"id": "S02", "start": 2.0, "end": 4.0, "seconds": 2.0, "motion": 5.0}],
            sheets=[],
        ))
        db.commit()
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    text, labels = _content_text(captured["messages"])
    #: 表里的两镜直接用,不现量(两刀口的片子若现量会出四个标注)。
    assert labels == ["【S01 · 0:00.0–0:02.0】", "【S02 · 0:02.0–0:04.0】"]
    #: 两条路都带镜头表:量好的刀口时长、判过的景别运镜。
    assert "【镜头表(刀口和时长是代码量的,准确" in text
    assert "全景" in text and "固定" in text


def test_frames_path_picks_shots_evenly_when_many(client, video_asset, monkeypatch) -> None:
    """镜比帧数上限多:均匀挑镜头,不超过这次的帧数预算。(4 秒片子的预算是 4 帧;6 镜挑 4)"""
    _add_vision_profile(client)
    shots = [{"id": f"S{i:02d}", "start": round((i - 1) * 4 / 6, 3), "end": round(i * 4 / 6, 3),
              "seconds": round(4 / 6, 3), "motion": 0.0}
             for i in range(1, 7)]
    with SessionLocal() as db:
        db.add(ShotBreakdown(asset_id=video_asset.id, workspace_id=video_asset.workspace_id,
                             lang="zh", params={}, meta={"duration": 4.0}, cuts=[], shots=shots, sheets=[]))
        db.commit()
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    _text, labels = _content_text(captured["messages"])
    assert len(labels) == 4, "6 镜按预算挑 4 帧"
    assert labels[0].startswith("【S01 ") and labels[-1].startswith("【S06 ")


def test_native_path_also_carries_shot_table(client, video_asset, monkeypatch) -> None:
    """原生那条路也带镜头表(ADR:两条路都带)。"""
    _add_vision_profile(client)
    with SessionLocal() as db:
        db.add(ShotBreakdown(
            asset_id=video_asset.id, workspace_id=video_asset.workspace_id, lang="zh",
            params={}, meta={"duration": 4.0}, cuts=[],
            shots=[{"id": "S01", "start": 0.0, "end": 4.0, "seconds": 4.0, "motion": 0.1,
                    "size": "close", "camera": ["static"], "frame": "主播特写"}],
            sheets=[],
        ))
        db.commit()
    captured: dict = {}

    def fake_call(db, profile, messages, call=None, **kwargs):
        captured["messages"] = messages
        return "看完了"

    monkeypatch.setattr(service, "call_vision_model", fake_call)
    from app.db.models import User

    with SessionLocal() as db:
        me = db.query(User).order_by(User.created_at).first().id
        result = service.analyze_asset(db, db.get(Asset, video_asset.id), "什么景别?",
                                       mode="native", user_id=me)
    assert result["mode"] == "native"
    prompt = captured["messages"][0]["content"][0]["text"]
    assert "【镜头表" in prompt and "特写" in prompt


def test_no_breakdown_falls_back_to_even_frames(client, video_asset, monkeypatch) -> None:
    """量刀口失败(比如替身视频读不出):回落均匀抽帧,分析照样出。"""
    _add_vision_profile(client)
    monkeypatch.setattr(service, "_breakdown_shots_for", lambda _db, _asset, _path: ([], None))
    captured = _captured_analyze(client, monkeypatch, video_asset.id)
    text, labels = _content_text(captured["messages"])
    assert "按时间均匀抽取" in text
    assert labels == []
