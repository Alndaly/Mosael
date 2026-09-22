from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.assets import proxies as proxyjobs
import app.domain.jobs as jobs_bus
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




def test_import_queues_proxy_and_job_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest disables proxies suite-wide; turn them on for this test but keep the
    # transcode synchronous (fake the thread) so the assertions are deterministic.
    monkeypatch.setattr(settings, "generate_proxies", True)
    # 线程由总线创建(start_proxy_job 现在走 dispatch_job),所以桩挂在总线那一侧。
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)

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
    proxyjobs._run_proxy(job.id, asset["id"])  # run the (faked) worker synchronously

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
    # 线程由总线创建(start_proxy_job 现在走 dispatch_job),所以桩挂在总线那一侧。
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
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


# ---------------------------------------------------------------------------
# 「这份素材会不会有代理」要由后端说出来,不能让前端用缺省值去猜
# ---------------------------------------------------------------------------


def test_关掉代理生成时_出参明说这份素材不会有代理(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`generate_proxies` 关掉时,后端既不建任务**也不写 `proxy_status`** —— 素材上什么都没说。

    前端于是读到空的 proxy_status,落进「未知一律当作还在转」那一档:遮罩上写「转码中,
    等一会儿就好」,而那是一件永远不会发生的事,外加每 2 秒轮询一次素材。遮罩上那个
    「重新生成代理」按钮打的 /proxy 在这种配置下同样是空操作 —— 自救手段也失效。

    `generate_proxies` 是**后端才知道**的开关,所以答案得跟着素材发出去。
    """
    monkeypatch.setattr(settings, "generate_proxies", False)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    video = tmp_path / "clip.mp4"
    make_video(video, 320, 240)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("clip.mp4", video.read_bytes(), "video/mp4")},
    ).json()

    assert asset["kind"] == "video"
    assert "proxy_status" not in asset["media_info"], "前提变了:后端现在会写状态,这条测试要重写"
    assert asset["proxy_expected"] is False, "素材上没有任何一处说得出「这台后端不生成代理」"
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == "proxy")).first() is None


def test_开着的时候视频说会有_图片说不会(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    video = tmp_path / "clip.mp4"
    make_video(video, 320, 240)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("clip.mp4", video.read_bytes(), "video/mp4")},
    ).json()
    assert asset["proxy_expected"] is True

    img = tmp_path / "pic.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-frames:v", "1", str(img)], check=True, timeout=30
    )
    picture = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"]},
        files={"file": ("pic.png", img.read_bytes(), "image/png")},
    ).json()
    # 图片不经代理:说「不会有」是对的,而前端对图片本来就直接判 ready,不会误报。
    assert picture["proxy_expected"] is False


def test_守卫只有一处(monkeypatch: pytest.MonkeyPatch) -> None:
    """建不建任务、和出参上那句话,必须是**同一个**判断 —— 不然它们迟早会漂。"""
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "generate_proxies", True)
    video = SimpleNamespace(kind="video", file_key="k")
    assert proxyjobs.proxies_possible(video) is True
    assert proxyjobs.proxies_possible(SimpleNamespace(kind="video", file_key="")) is False
    assert proxyjobs.proxies_possible(SimpleNamespace(kind="audio", file_key="k")) is False
    monkeypatch.setattr(settings, "generate_proxies", False)
    assert proxyjobs.proxies_possible(video) is False
