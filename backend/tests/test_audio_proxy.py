"""预览用的音频代理:有声音的素材都出一份小的 AAC,前端按 Range 只取要播的那几段。

此前预览混音器下的是**整份原文件**再 `decodeAudioData` 全解 —— 一小时的 WAV 下几百 MB、解出一点几 GB
的 PCM;解码失败还会每 40ms 重下一遍(无声的 AI 视频就是这样被无限重下的)。现在:

- 视频、音频入库都排音频代理(和画面代理同一个「proxy」任务);
- 源文件没有音轨记 `silent`,任务照样成功,启动扫描不再替它排队;
- 接口支持 Range(浏览器先读样本表,再只取样本字节);
- 旧素材没有音频代理:启动扫描按缺什么补什么,画面代理已在的不重转。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from app.domain.assets import proxies as proxyjobs
import app.domain.jobs as jobs_bus
from app.media import proxy as proxymod
from app.media.paths import resolve_key
from app.media.probe import probe_media
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


class _FakeThread:
    """总线起的线程换成空壳:任务在测试里同步跑,断言才确定。"""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def start(self) -> None:
        pass


def _tone(path: Path, seconds: float = 2.0) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=44100",
         "-ac", "1", str(path)],
        check=True, timeout=60,
    )


def _silent_video(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
         "-pix_fmt", "yuv420p", "-c:v", "mpeg4", str(path)],
        check=True, timeout=60,
    )


def _video_with_sound(path: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
         "-pix_fmt", "yuv420p", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)],
        check=True, timeout=60,
    )


def _import(client, ws_id: str, path: Path, mime: str) -> dict:
    return client.post(
        "/api/assets/import",
        data={"workspace_id": ws_id},
        files={"file": (path.name, path.read_bytes(), mime)},
    ).json()


def _run_queued_proxy_job(asset_id: str) -> Job:
    with SessionLocal() as db:
        job = db.scalars(select(Job).where(Job.kind == "proxy").order_by(Job.created_at.desc())).first()
        assert job is not None and job.payload["asset_id"] == asset_id
        job_id = job.id
    proxyjobs._run_proxy(job_id, asset_id)
    with SessionLocal() as db:
        return db.get(Job, job_id)


def _media_info(asset_id: str) -> dict:
    with SessionLocal() as db:
        return dict(db.get(Asset, asset_id).media_info)


def test_音频代理是48k立体声AAC_样本表在前(tmp_path: Path) -> None:
    src = tmp_path / "tone.wav"
    _tone(src)
    target = tmp_path / proxymod.AUDIO_PROXY_NAME
    assert proxymod.build_audio_proxy(src, target) is True

    info = probe_media(target)
    assert info.get("duration") == pytest.approx(2.0, abs=0.1)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name,sample_rate,channels",
         "-of", "csv=p=0", str(target)],
        capture_output=True, text=True, check=True, timeout=20,
    ).stdout.strip()
    assert probe == "aac,48000,2"
    data = target.read_bytes()
    # faststart:moov 在 mdat 前面 —— 浏览器读开头一小段就拿到样本表,不用先把整份下下来。
    assert 0 <= data.find(b"moov") < data.find(b"mdat")


def test_音频素材入库就排音频代理_任务跑完可按Range取(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    src = tmp_path / "voice.wav"
    _tone(src, seconds=3)
    asset = _import(client, ws["id"], src, "audio/wav")
    assert asset["kind"] == "audio"
    assert asset["media_info"]["audio_proxy_status"] == "pending"
    # 音频没有画面代理。
    assert "proxy_status" not in asset["media_info"]

    job = _run_queued_proxy_job(asset["id"])
    assert job.status == "succeeded"
    info = _media_info(asset["id"])
    assert info["audio_proxy_status"] == "ready"
    assert info["audio_proxy_key"].endswith("/" + proxymod.AUDIO_PROXY_NAME)

    whole = client.get(f"/api/assets/{asset['id']}/audio-proxy")
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "audio/mp4"
    part = client.get(f"/api/assets/{asset['id']}/audio-proxy", headers={"Range": "bytes=0-1023"})
    assert part.status_code == 206
    assert part.content == whole.content[:1024]


def test_没有音轨的视频记silent_任务照样成功_画面代理不受影响(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    # 画面代理用的 libx264 不一定在;这里只关心音频那一半,画面那一步换成「转成功了」。
    monkeypatch.setattr(proxyjobs, "build_proxy", lambda source, target, **_options: target.write_bytes(b"x") is not None)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    src = tmp_path / "ai.mp4"
    _silent_video(src)
    asset = _import(client, ws["id"], src, "video/mp4")
    assert asset["media_info"]["proxy_status"] == "pending"
    assert asset["media_info"]["audio_proxy_status"] == "pending"

    job = _run_queued_proxy_job(asset["id"])
    assert job.status == "succeeded", job.error
    info = _media_info(asset["id"])
    assert info["proxy_status"] == "ready"
    assert info["audio_proxy_status"] == "silent"
    assert "audio_proxy_key" not in info
    assert client.get(f"/api/assets/{asset['id']}/audio-proxy").status_code == 404


def test_有声视频两样代理一起出(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    monkeypatch.setattr(proxyjobs, "build_proxy", lambda source, target, **_options: target.write_bytes(b"x") is not None)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    src = tmp_path / "talk.mp4"
    _video_with_sound(src)
    asset = _import(client, ws["id"], src, "video/mp4")
    job = _run_queued_proxy_job(asset["id"])
    assert job.status == "succeeded", job.error
    assert job.result.keys() == {"proxy_key", "audio_proxy_key"}
    info = _media_info(asset["id"])
    assert (info["proxy_status"], info["audio_proxy_status"]) == ("ready", "ready")


def test_音频代理转失败_记failed_任务失败_画面代理那一半照样落ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "generate_proxies", True)
    monkeypatch.setattr(jobs_bus.threading, "Thread", _FakeThread)
    monkeypatch.setattr(proxyjobs, "build_proxy", lambda source, target, **_options: target.write_bytes(b"x") is not None)
    monkeypatch.setattr(proxyjobs, "build_audio_proxy", lambda source, target: False)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    src = tmp_path / "talk.mp4"
    _video_with_sound(src)
    asset = _import(client, ws["id"], src, "video/mp4")
    job = _run_queued_proxy_job(asset["id"])
    assert job.status == "failed"
    info = _media_info(asset["id"])
    assert (info["proxy_status"], info["audio_proxy_status"]) == ("ready", "failed")


def test_启动扫描给旧素材补音频代理_缺什么补什么_终态不再排(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """旧素材上没有 audio_proxy_status:这是「还没排过」,扫描替它排;画面代理已在盘上的不重转。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    def make(name: str, kind: str, info: dict, *, with_video_proxy: bool = False) -> str:
        with SessionLocal() as db:
            asset = Asset(workspace_id=ws["id"], name=name, kind=kind, file_key=f"media/{name}/{name}.bin", media_info=info)
            db.add(asset)
            db.commit()
            directory = resolve_key(asset.file_key).parent
            directory.mkdir(parents=True, exist_ok=True)
            if with_video_proxy:
                proxymod.proxy_path(directory).write_bytes(b"x")
            return asset.id

    old_video = make("old_video", "video", {"proxy_status": "ready"}, with_video_proxy=True)
    old_audio = make("old_audio", "audio", {})
    silent = make("silent", "video", {"proxy_status": "ready", "audio_proxy_status": "silent"}, with_video_proxy=True)
    broken = make("broken", "audio", {"audio_proxy_status": "failed"})
    image = make("image", "image", {})

    queued: dict[str, tuple[bool, bool]] = {}
    monkeypatch.setattr(proxyjobs.settings, "generate_proxies", True)
    monkeypatch.setattr(
        proxyjobs, "queue_proxy_job",
        lambda db, asset, *, created_by, video, audio: (video or audio) and queued.setdefault(asset.id, (video, audio)),
    )
    with SessionLocal() as db:
        proxyjobs.reconcile_missing_proxies(db)

    assert queued.get(old_video) == (False, True), "画面代理已在盘上,只该补音频"
    assert queued.get(old_audio) == (False, True)
    assert silent not in queued, "没有音轨是终态:启动扫描再排就是无限重试"
    assert broken not in queued
    assert image not in queued


def test_盘上已有音频代理而状态丢了_扫描把状态修回ready(monkeypatch: pytest.MonkeyPatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws["id"], name="a", kind="audio", file_key="media/a/a.wav", media_info={"audio_proxy_status": "pending"})
        db.add(asset)
        db.commit()
        directory = resolve_key(asset.file_key).parent
        directory.mkdir(parents=True, exist_ok=True)
        proxymod.audio_proxy_path(directory).write_bytes(b"x")
        asset_id = asset.id
    monkeypatch.setattr(proxyjobs.settings, "generate_proxies", True)
    with SessionLocal() as db:
        assert proxyjobs.reconcile_missing_proxies(db) == 0
        db.commit()
    info = _media_info(asset_id)
    assert info["audio_proxy_status"] == "ready"
    assert info["audio_proxy_key"].endswith(proxymod.AUDIO_PROXY_NAME)
