"""从视频抽音轨:新的音频素材、原视频不动、来源链记成 `audio`。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.assets.audio_extract import extract_audio_asset
from app.domain.assets.lineage import AUDIO
from app.media.ytdlp import _audio_only
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _video(path: Path) -> None:
    subprocess.run(
        [
            settings.ffmpeg, "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True, capture_output=True, timeout=120,
    )


def test_extract_audio_registers_a_new_audio_asset(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    _video(source)
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    original = client.post(
        "/api/assets/import",
        data={"workspace_id": workspace["id"]},
        files={"file": (source.name, source.read_bytes(), "video/mp4")},
    ).json()

    with SessionLocal() as db:
        asset = db.get(Asset, original["id"])
        assert asset is not None
        made = extract_audio_asset(db, asset)
        db.commit()
        db.refresh(made)
        assert made.id != asset.id
        assert made.kind == "audio"
        assert made.name.endswith("· 音轨")
        assert made.derived_from == [{"asset_id": asset.id, "op": AUDIO}]
        assert (settings.data_dir / made.file_key).is_file()
        assert asset.kind == "video"
        assert (settings.data_dir / asset.file_key).is_file()


def test_a_video_fallback_is_turned_into_audio_before_it_reaches_the_library(tmp_path: Path) -> None:
    source = tmp_path / "fallback.mp4"
    _video(source)

    made = _audio_only(source, tmp_path)

    assert made.suffix == ".m4a"
    assert made.is_file()
    assert made.stat().st_size > 0
    assert not source.exists()
