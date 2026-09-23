"""浏览器录的 webm 以毫秒计时,ffprobe 的 r_frame_rate/avg_frame_rate 都是 1000/1。
此前探测把它当成帧率,素材详情写着「1000fps」。"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset
from app.media.probe import _frame_rate, probe_media
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _millisecond_webm(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:duration=2",
         "-c:v", "libvpx", str(path)],
        check=True, timeout=60,
    )


def test_a_millisecond_time_base_is_not_reported_as_the_frame_rate(tmp_path: Path) -> None:
    # MediaRecorder 的 webm 里标称帧率和平均帧率都是 1000/1(ffmpeg 自己写的 webm 会带真实帧率,
    # 造不出这种文件,所以直接给探测结果):这时按帧数 ÷ 时长算。
    source = tmp_path / "rec.webm"
    _millisecond_webm(source)
    stream = {"r_frame_rate": "1000/1", "avg_frame_rate": "1000/1"}
    assert _frame_rate(source, stream, 2.0) == 25.0
    # 标称帧率说得通时照用,不数帧。
    assert _frame_rate(source, {"r_frame_rate": "120/1", "avg_frame_rate": "36/1"}, 2.0) == 120.0
    assert 20 <= probe_media(source)["fps"] <= 30


def test_the_migration_recomputes_implausible_frame_rates() -> None:
    """迁移 migrate-frame-rate-is-not-a-time-base:1000fps 的重算;正常的不动;再跑一次什么都不做。"""
    from app.db.migrations import _migrate_frame_rate_is_not_a_time_base

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    folder = settings.data_dir / "media" / "rec"
    folder.mkdir(parents=True, exist_ok=True)
    _millisecond_webm(folder / "rec.webm")
    broken = client.post("/api/assets", json={"workspace_id": ws["id"], "kind": "video", "name": "rec",
                                              "file_key": "media/rec/rec.webm", "media_info": {}}).json()
    fine = client.post("/api/assets", json={"workspace_id": ws["id"], "kind": "video", "name": "ok",
                                            "file_key": "media/rec/rec.webm", "media_info": {}}).json()
    with SessionLocal() as db:
        db.get(Asset, broken["id"]).media_info = {"fps": 1000.0, "duration": 2.0}
        db.get(Asset, fine["id"]).media_info = {"fps": 60.0, "duration": 2.0}
        db.commit()

    _migrate_frame_rate_is_not_a_time_base()
    with SessionLocal() as db:
        fixed = db.get(Asset, broken["id"]).media_info
        assert 20 <= fixed["fps"] <= 30 and fixed["duration"] == 2.0
        assert db.get(Asset, fine["id"]).media_info["fps"] == 60.0
        snapshot = json.dumps(fixed)

    _migrate_frame_rate_is_not_a_time_base()
    with SessionLocal() as db:
        assert json.dumps(db.get(Asset, broken["id"]).media_info) == snapshot
