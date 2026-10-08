"""预览代理转坏时说得出是哪种(体检 UM-33)。

此前任务详情里只有一句「ffmpeg 代理转码失败」:源文件坏了、编码不支持、磁盘满了,看起来都一样。现在带上 ffmpeg 说明原因的
那一行(core/text.blame_line 挑的,不是最后一行)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

import app.domain.jobs as jobs_bus
from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.assets import proxies as proxyjobs
from app.media import proxy as proxymod
from tests.util import fresh_client

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


class _FakeThread:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass


@needs_ffmpeg
def test_ffmpeg_报错退出时带着它说明原因的那一行(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"this is not a video at all" * 64)
    with pytest.raises(proxymod.ProxyFailed) as raised:
        proxymod.build_proxy(broken, tmp_path / "proxy.mp4")
    assert raised.value.reason, "ffmpeg 说了原因,不能丢"
    assert not (tmp_path / "proxy.mp4").exists()


@needs_ffmpeg
def test_任务失败原因里写着那一行(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1", "-pix_fmt", "yuv420p", str(source)],
        check=True, timeout=60,
    )
    asset_id = client.post("/api/assets/import", data={"workspace_id": workspace},
                           files={"file": ("v.mp4", source.read_bytes(), "video/mp4")}).json()["id"]
    with SessionLocal() as db:
        job_id = db.scalars(select(Job).where(Job.kind == "proxy")).first().id

    def broken(_source, _target, *, timeout):
        raise proxymod.ProxyFailed("moov atom not found")

    monkeypatch.setattr(proxyjobs, "build_proxy", broken)
    proxyjobs._run_proxy(job_id, asset_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and "moov atom not found" in (job.error or ""), job.error
    #: 原因按读的人的语言翻(带文案 key),ffmpeg 的原话原样夹在里面。此前写进去的是一句中文,英文界面里也是它。
    english = client.get(f"/api/jobs/{job_id}", headers={"Accept-Language": "en-US"}).json()["error"]
    assert english == "The preview proxy wasn't built: ffmpeg couldn't build the picture proxy (moov atom not found)", english
    chinese = client.get(f"/api/jobs/{job_id}", headers={"Accept-Language": "zh-CN"}).json()["error"]
    assert chinese == "预览代理没转成:ffmpeg 画面代理转码失败(moov atom not found)", chinese
