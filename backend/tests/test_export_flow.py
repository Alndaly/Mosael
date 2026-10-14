from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.media.scratch import scratch_root
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_test_video(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def _exported_file(client, workspace_id: str, tmp_path: Path) -> Path:
    """导出的产物 —— **从素材库取**,那才是用户拿到的那一份。

    此前这两条探的是 `exports/{job_id}.mp4` 那个中转文件。它现在跑完就删了:成功时内容
    已经拷进素材库,留着等于同一段成片在磁盘上存两份(实测某台机器攒了 445 MB);
    取消/失败时它是个半截,更不该留。
    """
    assets = client.get(f"/api/assets?workspace_id={workspace_id}").json()["items"]
    exported = next(item for item in assets if item["source"] == "exported")
    path = tmp_path / "exported.mp4"
    path.write_bytes(client.get(f"/api/assets/{exported['id']}/file").content)
    return path


def test_export_renders_mp4_with_gap_black(tmp_path: Path) -> None:
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()

    source = tmp_path / "src.mp4"
    make_test_video(source, 1.0)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": project["id"]},
        files={"file": ("src.mp4", source.read_bytes(), "video/mp4")},
    ).json()

    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main", "width": 320, "height": 180},
    ).json()
    video_track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    for start in (0.0, 1.5):  # 0.5s gap between the two clips
        client.post(
            f"/api/sequences/{sequence['id']}/clips",
            json={"track_id": video_track["id"], "asset_id": asset["id"], "timeline_start": start, "src_in": 0, "src_out": 1.0},
        )

    job = client.post(f"/api/sequences/{sequence['id']}/export").json()
    assert job["kind"] == "render"

    deadline = time.time() + 90
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.5)

    assert job["status"] == "succeeded", job.get("error")
    assert job["progress"] == 1.0

    # 中转文件跑完就该没了 —— 成品在素材库里,留着它就是第二份。
    assert not list((scratch_root() / "export").glob("*")), "导出的中转目录没清"
    assert _exported_file(client, ws["id"], tmp_path).stat().st_size > 0

    exported_asset = client.get(f"/api/assets?workspace_id={ws['id']}").json()["items"]
    exported = next(item for item in exported_asset if item["source"] == "exported")
    assert exported["kind"] == "video"
    assert abs(exported["media_info"]["duration"] - 2.5) < 0.2


def test_export_video_on_overlay_track_renders_with_audio(tmp_path: Path) -> None:
    """Regression: after the z-order flip, a video on an upper track with an empty bottom track
    used to fail export ("no clips to render") and drop its audio. The base must be the
    bottom-most track WITH clips, and the overlay video's audio must be mixed in."""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    source = tmp_path / "src.mp4"
    make_test_video(source, 1.5)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": project["id"]},
        files={"file": ("src.mp4", source.read_bytes(), "video/mp4")},
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main", "width": 320, "height": 180},
    ).json()
    video_track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": video_track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 1.5},
    )
    # Add a second video track — it becomes the (empty) bottom "base"; the clip is now an overlay.
    client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "video"})

    job = client.post(f"/api/sequences/{sequence['id']}/export").json()
    deadline = time.time() + 90
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.5)
    assert job["status"] == "succeeded", job.get("error")

    assert not list((scratch_root() / "export").glob("*"))
    output = _exported_file(client, ws["id"], tmp_path)
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
        capture_output=True, text=True,
    ).stdout
    assert "video" in streams and "audio" in streams  # the overlay video's audio survived export


def test_export_empty_sequence_rejected() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    res = client.post(f"/api/sequences/{sequence['id']}/export")
    assert res.status_code == 422


def test_friendly_render_error_names_corrupt_input() -> None:
    """导出失败时把 ffmpeg「打不开输入文件」翻成点名素材的中文(修复 code 187 无信息问题)。"""
    from app.domain.render import _friendly_render_error
    from app.media.render_executor import RenderExecutionError

    tail = (
        "[in#4] 0x00 at pos 36 invalid as first byte of an EBML number\n"
        "Error opening input file /Users/x/.mosael/media/assets/w/a/摄像头-1784712022145.webm.\n"
        "Error opening input files: End of file\n"
    )
    msg = _friendly_render_error(RenderExecutionError("FFmpeg exited with code 187", stderr_tail=tail))
    assert "摄像头-1784712022145.webm" in msg and "损坏或未录制完整" in msg

    # 认不出具体文件但有损坏迹象 → 泛化提示
    msg2 = _friendly_render_error(RenderExecutionError("FFmpeg exited with code 1", stderr_tail="moov atom not found"))
    assert "损坏或未录制完整" in msg2

    # 完全认不出 → 退回原始错误
    msg3 = _friendly_render_error(RenderExecutionError("FFmpeg exited with code 8", stderr_tail="weird"))
    assert "code 8" in msg3


def _audio_only_sequence(client, tmp_path: Path, seconds: float = 1.5) -> tuple[dict, dict]:
    """只有音频轨上有一段声音、视频轨空着的时间线(用户:「视频轨为空时导出报错」)。返回 (工作区, 序列)。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    source = tmp_path / "voice.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", str(source)],
        check=True, timeout=60,
    )
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": project["id"]},
        files={"file": ("voice.mp3", source.read_bytes(), "audio/mpeg")},
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main", "width": 320, "height": 180},
    ).json()
    audio_track = next(track for track in sequence["tracks"] if track["kind"] == "audio")
    client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": audio_track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": seconds},
    )
    return ws, sequence


def _wait(client, job: dict) -> dict:
    deadline = time.time() + 90
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.5)
    return job


def _streams(path: Path) -> list[str]:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.split()


def test_只有声音的时间线导出视频_画面是黑场(tmp_path: Path) -> None:
    """此前视频轨一空,导出就 422「Sequence has no clips to render」—— 那是渲染计划内部的话。
    底下没有画面时整条就是黑场(和中间的空档、尾巴上的空档同一种黑),声音照常混进去。"""
    client = fresh_client()
    ws, sequence = _audio_only_sequence(client, tmp_path)
    response = client.post(f"/api/sequences/{sequence['id']}/export")
    assert response.status_code == 200, response.text
    job = _wait(client, response.json())
    assert job["status"] == "succeeded", job.get("error")
    assert sorted(_streams(_exported_file(client, ws["id"], tmp_path))) == ["audio", "video"]


def test_只有声音的时间线导出声音(tmp_path: Path) -> None:
    """只有声音的时间线直接导出 mp3:没有画面那一路,也不起无头浏览器、不烧字。"""
    client = fresh_client()
    ws, sequence = _audio_only_sequence(client, tmp_path)
    response = client.post(f"/api/sequences/{sequence['id']}/export", json={"format": "mp3"})
    assert response.status_code == 200, response.text
    job = _wait(client, response.json())
    assert job["status"] == "succeeded", job.get("error")
    assert _streams(_exported_file(client, ws["id"], tmp_path)) == ["audio"]


def _video_sequence(client, tmp_path: Path) -> tuple[dict, dict]:
    """视频轨上一段 1 秒带声音的测试画面。返回 (工作区, 序列)。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    source = tmp_path / "src.mp4"
    make_test_video(source, 1.0)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": project["id"]},
        files={"file": ("src.mp4", source.read_bytes(), "video/mp4")},
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main", "width": 320, "height": 180},
    ).json()
    video_track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": video_track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 1.0},
    )
    return ws, sequence


def _codecs(path: Path) -> list[str]:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.split()


@pytest.mark.parametrize(
    "fmt,kind,codecs,media_type",
    [
        ("mp3", "audio", ["mp3,audio"], "audio/mpeg"),
        ("wav", "audio", ["pcm_s16le,audio"], "audio/wav"),
        ("m4a", "audio", ["aac,audio"], "audio/mp4"),
        ("mov", "video", ["aac,audio", "h264,video"], "video/quicktime"),
        ("webm", "video", ["opus,audio", "vp9,video"], "video/webm"),
    ],
)
def test_导出的格式就是选的格式(tmp_path: Path, fmt: str, kind: str, codecs: list[str], media_type: str) -> None:
    """选什么格式出什么文件:扩展名、编码、素材种类、下载时的类型都跟着走。音频格式只有声音(画面整条不建)。
    mov 不能像导入录屏那样被换成 mp4 —— 那样用户下载回来的又是 mp4。"""
    client = fresh_client()
    ws, sequence = _video_sequence(client, tmp_path)
    response = client.post(f"/api/sequences/{sequence['id']}/export", json={"format": fmt})
    assert response.status_code == 200, response.text
    job = _wait(client, response.json())
    assert job["status"] == "succeeded", job.get("error")

    assets = client.get(f"/api/assets?workspace_id={ws['id']}").json()["items"]
    exported = next(item for item in assets if item["source"] == "exported")
    assert exported["kind"] == kind
    download = client.get(f"/api/assets/{exported['id']}/file")
    assert download.headers["content-type"].startswith(media_type)
    assert f".{fmt}" in download.headers["content-disposition"]
    path = tmp_path / f"exported.{fmt}"
    path.write_bytes(download.content)
    assert sorted(_codecs(path)) == codecs
    assert abs(exported["media_info"]["duration"] - 1.0) < 0.15
