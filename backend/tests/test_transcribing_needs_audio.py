"""没有音轨的素材,转写要当场说清楚,而不是把 ffmpeg 的话原样倒出来。

用户看到的是这个:

    音频提取失败: [out#0/wav @ 0x80cc40180] Output file does not contain any stream
    Error opening output file /var/folders/.../audio.wav.
    Error opening output files: Invalid argument

翻译过来是"这个素材没有音轨"—— 提取命令带 `-vn`(去掉视频),源里又没有音频,于是输出文件一条流
都没有,ffmpeg 拒绝写。而屏幕录制、无声的生成视频、纯画面素材本来就没有音轨,这是**正常输入**,
不是异常。

判据在项目里早就有了(`media.probe.probe_has_audio`,渲染路径一直在用),只是转写这条路没用它。
于是一个能提前一秒说清的事实,变成了一段没人看得懂的 ffmpeg stderr。

**要在建任务之前就说** —— 而不是起一个任务、跑一段、再失败:那样用户还要去任务列表里找原因。
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from app.audio import service
from app.core.db import SessionLocal
from app.db.models import Asset, Job
from tests.util import fresh_client


def _asset(client, path: pathlib.Path, name: str) -> str:
    workspace_id = client.get("/api/workspaces").json()[0]["id"]
    with SessionLocal() as db:
        asset = Asset(workspace_id=workspace_id, name=name, kind="video", file_key=str(path))
        db.add(asset)
        db.commit()
        return asset.id


def _silent_video(tmp_path: pathlib.Path) -> pathlib.Path:
    """一段**没有音轨**的视频 —— 屏幕录制、无声生成视频都是这个形状。"""
    out = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True, timeout=120,
    )
    return out


def test_it_says_there_is_no_audio(tmp_path) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    asset_id = _asset(client, _silent_video(tmp_path), "屏幕录制")

    with SessionLocal() as db:
        with pytest.raises(service.AsrError) as caught:
            service.start_transcription(db, asset_id, created_by=None)

    message = str(caught.value)
    assert "音轨" in message, f"没说清是没有音轨:{message}"
    assert "ffmpeg" not in message.lower() and "stream" not in message.lower(), f"把 ffmpeg 的话倒出来了:{message}"


def test_it_refuses_before_creating_a_job(tmp_path) -> None:
    """在建任务之前就说 —— 否则用户要去任务列表里翻原因。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    asset_id = _asset(client, _silent_video(tmp_path), "屏幕录制")

    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(service.AsrError):
            service.start_transcription(db, asset_id, created_by=None)
        assert db.query(Job).count() == before, "已经起了一个注定失败的任务"


def test_a_video_with_audio_still_goes_through(tmp_path) -> None:
    """这道闸只挡没有音轨的 —— 有音轨的照常建任务。"""
    out = tmp_path / "withaudio.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
         "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-shortest", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True, timeout=120,
    )
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    asset_id = _asset(client, out, "有声的")

    with SessionLocal() as db:
        job = service.start_transcription(db, asset_id, created_by=None)
        assert job.kind == "transcribe"
