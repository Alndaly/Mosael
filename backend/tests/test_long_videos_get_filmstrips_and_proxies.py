"""长片 / 4K 也有帧条和预览代理(MED-7)。

此前:
- 帧条用 `fps=12/时长` 让 ffmpeg 把整条片子解一遍:4K HEVC 10-bit 约 0.3 秒 / 秒素材,6 分钟以上撞 120 秒超时;失败
  不记,画板每挂一次帧条就再解一遍,同一段素材的几个请求各起一份 ffmpeg;
- 预览代理一律 600 秒超时:28 分钟以上的 4K 永远没有代理,提示只是「ffmpeg 代理转码失败」,看不出是超时。
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.assets import proxies as proxyjobs
import app.domain.jobs as jobs_bus
from app.media import filmstrip
from app.media import proxy as proxymod
from app.media.paths import resolve_key
from app.media.probe import probe_media
from tests.util import fresh_client

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _video(path: Path, seconds: float = 6.0) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=25:duration={seconds}",
         "-g", "50", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60,
    )
    return path


@needs_ffmpeg
def test_帧条跳着取十二格_拼成一张(tmp_path: Path) -> None:
    source = _video(tmp_path / "v.mp4")
    made = filmstrip.generate_filmstrip(source, "video", tmp_path)

    assert made is not None
    info = probe_media(made)
    assert info["height"] == filmstrip.FRAME_HEIGHT
    assert info["width"] == filmstrip.FRAMES * 86, info  # 320x180 缩到高 48 → 每格宽 86(偶数)


def test_帧条不整段解码_每一格在输入端跳到那个时刻(monkeypatch, tmp_path: Path) -> None:
    """耗时跟片长无关的关键:`-ss` 在 `-i` 前面,而且不用 `fps=` 把整条片子解一遍。"""
    source = tmp_path / "long.mp4"
    source.write_bytes(b"x")
    seen: list[list[str]] = []
    monkeypatch.setattr(filmstrip, "_duration", lambda _source: 3600.0)
    monkeypatch.setattr(filmstrip, "run_logged", lambda args, **_kw: seen.append(list(args)))

    filmstrip.generate_filmstrip(source, "video", tmp_path)

    [args] = seen
    seeks = [index for index, arg in enumerate(args) if arg == "-ss"]
    assert len(seeks) == filmstrip.FRAMES
    assert all(args[index + 2] == "-i" for index in seeks), "-ss 要放在 -i 前面(输入端跳)"
    assert not any("fps=" in arg for arg in args), "按 fps 取帧要把整条片子解一遍"
    assert float(args[seeks[-1] + 1]) < 3600.0, "最后一格不能落在片尾之外"


def test_做不出来记下来_源文件不变就不再重试_换了才重试(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not a video")
    runs: list[int] = []
    monkeypatch.setattr(filmstrip, "_duration", lambda _source: 10.0)

    def fails(args, **_kw):
        runs.append(1)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(filmstrip, "run_logged", fails)

    assert filmstrip.generate_filmstrip(source, "video", tmp_path) is None
    assert filmstrip.generate_filmstrip(source, "video", tmp_path) is None
    assert len(runs) == 1, "做不出来的每次打开剪辑面板都再跑一遍 ffmpeg"

    source.write_bytes(b"replaced with something else")
    filmstrip.generate_filmstrip(source, "video", tmp_path)
    assert len(runs) == 2, "源文件换了要再试"


def test_同一段素材同时要好几次_只做一份(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "v.mp4"
    source.write_bytes(b"x")
    made: list[int] = []

    def slow_make(_source: Path, target: Path) -> Path:
        made.append(1)
        time.sleep(0.3)
        target.write_bytes(b"\xff\xd8\xff\xd9")
        return target

    monkeypatch.setattr(filmstrip, "_make", slow_make)
    threads = [threading.Thread(target=filmstrip.generate_filmstrip, args=(source, "video", tmp_path)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert made == [1], f"同一段素材起了 {len(made)} 份"


# --------------------------------------------------------------------- 预览代理


def test_代理时限按时长放宽() -> None:
    assert proxymod.proxy_timeout(None) == proxymod.PROXY_TIMEOUT_FLOOR_SECONDS
    assert proxymod.proxy_timeout(60) == proxymod.PROXY_TIMEOUT_FLOOR_SECONDS, "短片照旧十分钟"
    assert proxymod.proxy_timeout(3600) >= 3 * 3600, "一小时的片子要给到三小时"


class _FakeThread:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass


@needs_ffmpeg
def test_长片的代理按时长给时限_超时和转坏分开说(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _video(tmp_path / "v.mp4", 2.0)
    asset_id = client.post("/api/assets/import", data={"workspace_id": workspace},
                           files={"file": ("v.mp4", source.read_bytes(), "video/mp4")}).json()["id"]
    with SessionLocal() as db:
        asset = db.get(Asset, asset_id)
        asset.media_info = {**asset.media_info, "duration": 3600.0}  # 当它是一小时的片子
        db.commit()
        job_id = db.scalars(select(Job).where(Job.kind == "proxy")).first().id
    limits: list[float] = []

    def too_slow(_source, target, *, timeout):
        limits.append(timeout)
        raise proxymod.ProxyTimedOut("slow")

    monkeypatch.setattr(proxyjobs, "build_proxy", too_slow)
    proxyjobs._run_proxy(job_id, asset_id)

    assert limits == [proxymod.proxy_timeout(3600.0)]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and "超时" in (job.error or ""), job.error
        assert db.get(Asset, asset_id).media_info["proxy_status"] == "failed"
    assert not (resolve_key(f"media/assets/{workspace}/{asset_id}/proxy.mp4")).exists()
