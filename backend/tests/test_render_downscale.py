"""降分辨率导出:以序列像素记的量 —— 字幕 / 花字的字号、描边、阴影,画面元素投影的模糊和偏移 ——
跟着输出比例缩。此前只有字幕字号缩了:1080 的竖屏导成 720,花字比预览大一半,投影偏出去一大截。

先看计划里的数(经 build_plan_for_sequence,和导出接口同一条路),再真渲两份比像素。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Sequence, Track
from app.domain.render import build_plan_for_sequence
from app.media.render_executor import render_still
from app.media.render_plan import build_render_plan
from tests.render_text_paths import use_browser, use_libass
from tests.util import fresh_client

HAS_FFMPEG = shutil.which(settings.ffmpeg) is not None
SHADOW = {"shadow": {"enabled": True, "color": "#000000", "opacity": 1.0, "blur": 24, "offset_x": 30, "offset_y": 45}}
HUAZI = {"font_size": 96, "stroke_width": 4, "shadow": 3}


def test_导出_720p_时字号描边阴影都按比例缩() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    with SessionLocal() as db:
        video = Asset(workspace_id=ws, name="v.mp4", kind="video", file_key="v.mp4")
        sequence = Sequence(workspace_id=ws, project_id=project, name="S", width=1080, height=1920,
                            subtitle_style={"font_size": 48})
        base, upper, subs = (Track(sequence=sequence, kind="video", name="V1", position=2),
                             Track(sequence=sequence, kind="video", name="V2", position=1),
                             Track(sequence=sequence, kind="subtitle", name="S1", position=0))
        db.add_all([video, sequence, base, upper, subs])
        db.flush()
        db.add_all([
            Clip(workspace_id=ws, sequence_id=sequence.id, track_id=base.id, asset_id=video.id,
                 timeline_start=0, src_in=0, src_out=4),
            Clip(workspace_id=ws, sequence_id=sequence.id, track_id=upper.id, asset_id=video.id,
                 timeline_start=0, src_in=0, src_out=4, effects={"appearance": SHADOW},
                 transform={"scale": 0.4}),
            Clip(workspace_id=ws, sequence_id=sequence.id, track_id=upper.id, asset_id=None,
                 timeline_start=0, src_in=0, src_out=4, text_override="花字", effects={"text_style": HUAZI}),
            Clip(workspace_id=ws, sequence_id=sequence.id, track_id=subs.id, asset_id=None,
                 timeline_start=0, src_in=0, src_out=4, text_override="字幕"),
        ])
        db.commit()
        sequence_id = sequence.id
    with SessionLocal() as db:
        original = build_plan_for_sequence(db, sequence_id, {"resolution": "original"})
        small = build_plan_for_sequence(db, sequence_id, {"resolution": "720p"})
    assert (small.output.width, small.output.height) == (720, 1280)
    k = 720 / 1080
    assert small.subtitle_style.font_size == pytest.approx(48 * k, abs=0.01)
    huazi = small.text_overlays[0].style
    assert (huazi.font_size, huazi.stroke_width, huazi.shadow) == pytest.approx((96 * k, 4 * k, 3 * k), abs=0.01)
    shadow = small.overlays[0].appearance.shadow
    assert (shadow.blur, shadow.offset_x, shadow.offset_y) == pytest.approx((24 * k, 30 * k, 45 * k), abs=0.01)
    # 原尺寸导出一点不动
    assert original.text_overlays[0].style.font_size == 96 and original.overlays[0].appearance.shadow.blur == 24


def _render(tmp_path: Path, width: int, height: int, *, text: bool) -> np.ndarray:
    """白底、正中一块带硬投影的红色画中画;text=True 时再加一行花字。"""
    for name, colour in (("white", "white"), ("red", "red")):
        src = tmp_path / f"{name}.mp4"
        if not src.exists():
            subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color={colour}:s=320x180:r=10:d=2",
                            "-pix_fmt", "yuv420p", str(src)], check=True, timeout=30)
    k = width / 1280
    #: 投影按画面像素算(契约 clip-shadow-cases):不随片段的 scale 缩,偏移 60/90 就是序列画幅里的 60/90 像素。
    hard = {"shadow": {**SHADOW["shadow"], "blur": 0, "offset_x": 60, "offset_y": 90}}
    plan = build_render_plan(
        sequence_id="s", revision=1, width=width, height=height, fps=10, pixel_scale=k,
        clips=[{"id": "b", "asset_id": "w", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"w": {"file_key": "white.mp4"}, "r": {"file_key": "red.mp4"}},
        overlay_clips=[{"id": "o", "asset_id": "r", "timeline_start": 0, "src_in": 0, "src_out": 2,
                        "transform": {"scale": 0.5, "y": -0.3}, "effects": {"appearance": hard}}],
        text_overlays=[{"id": "t", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "花字",
                        "effects": {"text_style": {**HUAZI, "color": "#0000ff", "stroke_width": 0, "shadow": 0}},
                        "transform": {"y": 0.5}}] if text else [],
    )
    frame = tmp_path / f"f{width}.png"
    render_still(plan, lambda key: tmp_path / key, frame, 1.0)
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True, timeout=30).stdout
    return np.frombuffer(raw, np.uint8).reshape(height, width, 3).astype(int)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_投影的偏移跟着输出缩(tmp_path) -> None:
    offsets = {}
    for width, height in ((1280, 720), (640, 360)):
        rgb = _render(tmp_path, width, height, text=False)
        red = _bbox((rgb[..., 0] > 180) & (rgb[..., 1] < 80))
        black = _bbox(rgb.sum(axis=2) < 120)
        offsets[width] = (black[2] - red[2], black[3] - red[3])
    assert offsets[1280] == pytest.approx((60, 90), abs=2)
    assert offsets[640] == pytest.approx((30, 45), abs=2), f"半尺寸导出的投影偏移 {offsets[640]},该是一半"


@pytest.mark.parametrize("path", ["libass", "browser"])
def test_花字跟着输出缩(path, tmp_path, monkeypatch) -> None:
    (use_libass if path == "libass" else use_browser)(monkeypatch)
    heights = {}
    for width, height in ((1280, 720), (640, 360)):
        rgb = _render(tmp_path, width, height, text=True)
        blue = (rgb[..., 2] > 150) & (rgb[..., 0] < 100) & (rgb[..., 1] < 100)
        x0, y0, x1, y1 = _bbox(blue)
        heights[width] = y1 - y0
    assert heights[640] / heights[1280] == pytest.approx(0.5, abs=0.06), f"花字高度 {heights}"
