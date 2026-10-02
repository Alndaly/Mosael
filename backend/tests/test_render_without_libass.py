"""没有 libass 的 ffmpeg(Homebrew 的 core 版就是)烧不了 ASS。

- 文字能走浏览器渲 PNG 那条路时,**整条导出不碰 libass**:滤镜图里没有 `subtitles=`,真跑得通;
- 两条路都不通时,**建任务之前**就说清楚是缺 libass、该装什么,而不是等任务跑起来,
  ffmpeg 报一句「No such filter: 'subtitles'」。

「精简版 ffmpeg」用一个包一层的脚本模拟:`-filters` 的清单里删掉 subtitles/ass,其余原样交给真 ffmpeg ——
真正跑的仍是真 ffmpeg,滤镜图里要是还有 `subtitles=` 照样会被真 ffmpeg 接下来,所以断言滤镜图本身。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Job, Sequence, Track
from app.media import render_executor
from app.media.render_executor import (
    RenderExecutionError,
    build_ffmpeg_command,
    compose_text_layers,
    ensure_text_can_burn,
)
from app.media.render_plan import build_render_plan
from tests.util import fresh_client

REAL_FFMPEG = shutil.which(settings.ffmpeg) or shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(REAL_FFMPEG is None, reason="ffmpeg not installed")


@pytest.fixture
def slim_ffmpeg(tmp_path, monkeypatch) -> str:
    script = tmp_path / "ffmpeg-slim"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-hide_banner" ] && [ "$2" = "-filters" ]; then\n'
        f'  "{REAL_FFMPEG}" -hide_banner -filters | grep -v -E " (subtitles|ass) "\n'
        "  exit 0\n"
        "fi\n"
        f'exec "{REAL_FFMPEG}" "$@"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "ffmpeg", str(script))
    return str(script)


def _plan_with_subtitle(src_key: str):
    return build_render_plan(
        sequence_id="s", revision=1, width=160, height=90, fps=10,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 1}],
        assets={"a": {"file_key": src_key}},
        subtitle_clips=[{"id": "t1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 1, "text_override": "你好"}],
    )


def test_探测认得出有没有_libass(slim_ffmpeg) -> None:
    assert render_executor.ffmpeg_has_libass(slim_ffmpeg) is False
    listed = subprocess.run([REAL_FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    assert render_executor.ffmpeg_has_libass(REAL_FFMPEG) is (" subtitles " in listed)


def test_文字走浏览器那条路时_不碰_libass_真跑得通(slim_ffmpeg, tmp_path) -> None:
    src = tmp_path / "src.mp4"
    subprocess.run([REAL_FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x90:r=10:d=1",
                    "-pix_fmt", "yuv420p", str(src)], check=True, timeout=30)
    png = tmp_path / "sub0.png"
    subprocess.run([REAL_FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=white:s=40x10",
                    "-frames:v", "1", str(png)], check=True, timeout=30)
    plan = _plan_with_subtitle(src.name)
    out = tmp_path / "out.mp4"
    command = build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True,
                                   text_layers=compose_text_layers(plan, {"subtitles": [(png, 40, 10)]}, tmp_path))
    assert "subtitles=" not in " ".join(command)
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    assert out.stat().st_size > 0


def test_两条路都不通_说清楚缺什么(slim_ffmpeg, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "text_rasterize", False)
    plan = _plan_with_subtitle("src.mp4")
    with pytest.raises(RenderExecutionError) as caught:
        ensure_text_can_burn(plan)
    assert caught.value.key == "renderErr_noLibass" and "libass" in str(caught.value)
    # 绕过了建任务前那一道的(取帧、浏览器在任务里才起不来的导出)走到回落 ASS 那一步,也是同一句话。
    with pytest.raises(RenderExecutionError, match="libass"):
        render_executor.render_still(plan, lambda key: tmp_path / key, tmp_path / "frame.jpg", 0.5)


def test_没字要烧_不需要_libass(slim_ffmpeg, monkeypatch) -> None:
    monkeypatch.setattr(settings, "text_rasterize", False)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=160, height=90, fps=10,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 1}],
        assets={"a": {"file_key": "src.mp4"}},
    )
    ensure_text_can_burn(plan)


def test_导出接口在建任务之前就拒_422(slim_ffmpeg, monkeypatch) -> None:
    client = fresh_client()
    monkeypatch.setattr(settings, "text_rasterize", False)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    with SessionLocal() as db:
        video = Asset(workspace_id=ws, project_id=project, name="v.mp4", kind="video", file_key="v.mp4")
        db.add(video)
        sequence = Sequence(workspace_id=ws, project_id=project, name="S")
        v1 = Track(sequence=sequence, kind="video", name="V1", position=0)
        s1 = Track(sequence=sequence, kind="subtitle", name="S1", position=1)
        db.add_all([sequence, v1, s1])
        db.flush()
        db.add(Clip(workspace_id=ws, sequence_id=sequence.id, track_id=v1.id, asset_id=video.id,
                    timeline_start=0, src_in=0, src_out=2))
        db.add(Clip(workspace_id=ws, sequence_id=sequence.id, track_id=s1.id, asset_id=None,
                    timeline_start=0, src_in=0, src_out=2, text_override="字幕"))
        db.commit()
        sequence_id = sequence.id
    response = client.post(f"/api/sequences/{sequence_id}/export", json={})
    assert response.status_code == 422, response.text
    assert "libass" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.kind == "render").count() == 0, "不该建出一个注定失败的任务"


def test_slim_脚本本身可用(slim_ffmpeg) -> None:
    """护住上面几条的前提:包一层之后真 ffmpeg 仍能被调起来。"""
    assert os.access(slim_ffmpeg, os.X_OK)
    assert subprocess.run([slim_ffmpeg, "-hide_banner", "-version"], capture_output=True).returncode == 0
