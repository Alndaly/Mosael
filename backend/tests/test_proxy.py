from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.media import proxy as proxymod
from app.media.probe import probe_media
from tests.util import fresh_client


def _has_libx264() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    return "libx264" in out.stdout


pytestmark = pytest.mark.skipif(not _has_libx264(), reason="ffmpeg with libx264 not installed")


def make_video(path: Path, width: int, height: int, seconds: float = 1.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=size={width}x{height}:rate=30:duration={seconds}",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=60,
    )


class _FakeThread:
    """Stand-in for threading.Thread so start_proxy_job doesn't transcode async."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass


def test_build_proxy_caps_height_and_is_decodable(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    make_video(src, 1920, 1080)
    target = tmp_path / "proxy.mp4"

    assert proxymod.build_proxy(src, target) is True
    info = probe_media(target)
    assert info["height"] == proxymod.PROXY_HEIGHT  # capped at 720
    assert info["width"] % 2 == 0  # even dimensions (yuv420p requirement)
    assert info["width"] == 1280  # 1920×1080 → 1280×720, aspect preserved


def test_build_proxy_never_upscales(tmp_path: Path) -> None:
    src = tmp_path / "small.mp4"
    make_video(src, 640, 360)
    target = tmp_path / "proxy.mp4"
    assert proxymod.build_proxy(src, target) is True
    assert probe_media(target)["height"] == 360  # min(720, 360) = 360


def test_build_export_proxy_keeps_native_resolution(tmp_path: Path) -> None:
    src = tmp_path / "src.mp4"
    make_video(src, 1920, 1080)
    target = tmp_path / "export-proxy.mp4"
    assert proxymod.build_export_proxy(src, target) is True
    info = probe_media(target)
    # Full resolution preserved — NOT capped to 720 like the preview proxy.
    assert info["width"] == 1920
    assert info["height"] == 1080


def test_ensure_export_proxy_builds_serves_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(proxymod.threading, "Thread", _FakeThread)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    src = tmp_path / "v.mp4"
    make_video(src, 640, 360)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("v.mp4", src.read_bytes(), "video/mp4")},
    ).json()

    # No export proxy until the orchestrator builds one — endpoint 404s.
    assert client.get(f"/api/assets/{asset['id']}/export-proxy").status_code == 404

    with SessionLocal() as db:
        path = proxymod.ensure_export_proxy(db, db.get(Asset, asset["id"]))
        assert path is not None and path.is_file()
        assert proxymod.export_proxy_status(db.get(Asset, asset["id"])) == "ready"

    # Now served; distinct from the preview proxy (still absent — proxy job never ran here).
    res = client.get(f"/api/assets/{asset['id']}/export-proxy")
    assert res.status_code == 200
    assert res.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/assets/{asset['id']}/proxy").status_code == 404

    # Cache hit: a second ensure short-circuits to the file on disk, never re-transcoding.
    def _no_rebuild(*_a: object, **_k: object) -> bool:
        raise AssertionError("cached export proxy must not be rebuilt")

    monkeypatch.setattr(proxymod, "build_export_proxy", _no_rebuild)
    with SessionLocal() as db:
        again = proxymod.ensure_export_proxy(db, db.get(Asset, asset["id"]))
        assert again is not None and again.is_file()


def test_import_queues_proxy_and_job_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest disables proxies suite-wide; turn them on for this test but keep the
    # transcode synchronous (fake the thread) so the assertions are deterministic.
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(proxymod.threading, "Thread", _FakeThread)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    src = tmp_path / "v.mp4"
    make_video(src, 1920, 1080)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("v.mp4", src.read_bytes(), "video/mp4")},
    ).json()
    assert asset["kind"] == "video"
    # Import queued a proxy and flagged the asset pending.
    assert asset["media_info"]["proxy_status"] == "pending"

    with SessionLocal() as db:
        job = db.scalars(select(Job).where(Job.kind == "proxy")).first()
        assert job is not None
    proxymod._run_proxy(job.id, asset["id"])  # run the (faked) worker synchronously

    # Asset now reports ready + carries a proxy_key; the endpoint serves the file.
    refreshed = next(a for a in client.get(f"/api/assets?workspace_id={ws['id']}").json() if a["id"] == asset["id"])
    assert refreshed["media_info"]["proxy_status"] == "ready"
    assert refreshed["media_info"]["proxy_key"].endswith("/proxy.mp4")

    res = client.get(f"/api/assets/{asset['id']}/proxy")
    assert res.status_code == 200
    assert res.headers["content-type"] == "video/mp4"

    with SessionLocal() as db:
        done = db.get(Job, job.id)
        assert done.status == "succeeded"


def test_non_video_import_skips_proxy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(proxymod.threading, "Thread", _FakeThread)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    img = tmp_path / "pic.png"
    make_video(tmp_path / "tmp.mp4", 320, 240)  # reuse ffmpeg to make a png frame
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp_path / "tmp.mp4"), "-frames:v", "1", str(img)], check=True, timeout=30)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("pic.png", img.read_bytes(), "image/png")},
    ).json()
    assert asset["kind"] == "image"
    assert "proxy_status" not in asset["media_info"]  # images never get a proxy
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == "proxy")).first() is None
