"""双语分两条字幕轨:两行都在字幕样式指定的位置,原文在上、译文在下 —— 和同一条轨里写两行是同一个画面。

前一版(4a5ed5ac1)让第二条字幕轨换到画面另一头:底部样式下译文跑到画面顶上。用户要的是两行都在底部。
现在的规则:同一时刻各字幕轨上在场的字**合成一框**,一道一行(一条字幕自己有几行就占几行),框整体按
字幕样式定位 —— 底部时框的下沿不动、往上长,顶部时上沿不动、往下长。道的顺序就是字幕轨在时间线上的
上下顺序(position 升序):新建的字幕轨缺省放在最下面,所以先有的原文轨默认在上;要换就在时间线上挪轨道。

规则本身由 contracts/text-layer-cases.json(合成哪几行、什么顺序、哪段时间)与 subtitle-cases.json
(框放在哪)钉住;这里在真时间线 → 渲染计划 → ffmpeg 命令 → 真渲出来的帧这条路上看。验收判据:
**分两条轨的成片 = 同一条轨里写两行的成片**,两条导出路径(按预览 CSS 渲染的 PNG、libass 回落)都逐像素相同。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.render import build_plan_for_sequence
from app.media.render_executor import build_ffmpeg_command, render_still
from app.media.render_plan import build_render_plan
from tests.util import fresh_client


def _sequence(client) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 4.0})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    return ws, sid


def _subtitle_track(client, sid: str, cues: list[tuple[str, float, float]]) -> str:
    seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    track = [t for t in seq["tracks"] if t["kind"] == "subtitle"][-1]["id"]
    response = client.post(
        f"/api/sequences/{sid}/subtitles/generate",
        json={"track_id": track, "cues": [{"text": text, "timeline_start": start, "duration": dur} for text, start, dur in cues]},
    )
    assert response.status_code == 200, response.text
    return track


def _plan(sid: str):
    with SessionLocal() as db:
        return build_plan_for_sequence(db, sid)


def _frames(plan) -> list[tuple[float, float, str]]:
    return [(item.start, item.duration, item.text) for item in plan.subtitles]


def test_两条字幕轨合成一框_先建的原文轨在上() -> None:
    client = fresh_client()
    _ws, sid = _sequence(client)
    _subtitle_track(client, sid, [("你好", 0.0, 2.0)])
    _subtitle_track(client, sid, [("Hello", 0.0, 2.0)])
    assert _frames(_plan(sid)) == [(0.0, 2.0, "你好\nHello")]


def test_把译文轨挪到上面_框里的顺序跟着换() -> None:
    client = fresh_client()
    _ws, sid = _sequence(client)
    _subtitle_track(client, sid, [("你好", 0.0, 2.0)])
    english = _subtitle_track(client, sid, [("Hello", 0.0, 2.0)])
    assert client.patch(f"/api/sequences/{sid}/tracks/{english}/move", json={"direction": "up"}).status_code == 200
    assert _frames(_plan(sid)) == [(0.0, 2.0, "Hello\n你好")]


def test_时间错开时按在场的字切段_只剩一道就只有一行() -> None:
    client = fresh_client()
    _ws, sid = _sequence(client)
    _subtitle_track(client, sid, [("你好", 0.0, 3.0)])
    _subtitle_track(client, sid, [("Hello", 1.0, 3.0)])
    assert _frames(_plan(sid)) == [(0.0, 1.0, "你好"), (1.0, 2.0, "你好\nHello"), (3.0, 1.0, "Hello")]


def test_分两条轨的计划和同一条轨写两行的计划一样() -> None:
    """验收判据落在计划这一层:两种写法交给执行器的字幕一模一样,后面两条导出路径自然画出同一个画面。"""
    client = fresh_client()
    _ws, two_tracks = _sequence(client)
    _subtitle_track(client, two_tracks, [("你好", 0.0, 2.0)])
    _subtitle_track(client, two_tracks, [("Hello", 0.0, 2.0)])
    _ws, one_track = _sequence(client)
    _subtitle_track(client, one_track, [("你好\nHello", 0.0, 2.0)])
    assert _plan(two_tracks).subtitles == _plan(one_track).subtitles


def test_导出命令里是一框字幕_用序列的字幕样式定位(tmp_path: Path) -> None:
    client = fresh_client()
    _ws, sid = _sequence(client)
    _subtitle_track(client, sid, [("你好", 0.0, 2.0)])
    _subtitle_track(client, sid, [("Hello", 0.0, 2.0)])
    plan = _plan(sid)
    # 按预览 CSS 渲染的 PNG 那条路:只有一张字幕图(两行一框),按序列的字幕样式(底部 8%)放:下沿贴 1080 − 86。
    pngs = {"subtitles": [(tmp_path / "s0.png", 400, 103)], "text_overlays": []}
    graph = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4", text_pngs=pngs))
    assert re.findall(r"\[stin\d+\]overlay=x=(\d+):y=(\d+)", graph) == [("760", str(1080 - 86 - 103))], graph

    # libass 回落那条路:一条 Dialogue,两行用 \N 连起来,沿用 Default 样式(没有换道用的 \an 覆盖)。
    build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4")
    ass = (tmp_path / "o.ass").read_text(encoding="utf-8")
    dialogues = [line for line in ass.splitlines() if line.startswith("Dialogue:") and ",Default," in line]
    assert dialogues == ["Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,你好\\NHello"]


# ───────────────────────────── 真渲:两条导出路径各量一帧 ─────────────────────────────
#
# 用 render_still —— 和成片同一条 ffmpeg 命令(先把字幕渲成 PNG,拿不到 Chromium 时回落 libass)。
# 字是白的、底是纯绿、字幕不带背景框:白色像素就是字的墨迹。两行用同一个字、不同字数,
# 墨迹的行带一宽一窄,宽窄就认得出哪行是哪行;两行字形一样,行带顶到顶的距离就是行距。

_W, _H = 1920, 1080
_ORIGINAL, _TRANSLATION = "字字", "字字字字字字"


def _chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).is_file()
    except Exception:
        return False


def _libass_ready() -> bool:
    try:
        out = subprocess.run([settings.ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return " subtitles " in out.stdout


needs_libass = pytest.mark.skipif(
    not _libass_ready(), reason="ffmpeg 没带 libass(没有 subtitles 滤镜);MOSAEL_FFMPEG 指向完整版"
)
needs_chromium = pytest.mark.skipif(
    not _chromium_ready(), reason="Playwright Chromium 没装(uv run playwright install chromium)"
)


@pytest.fixture
def stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """纯绿底图 + 一份最小 dist(字幕用系统字体栈,不需要 app 的 @font-face;TextRasterizer 只要 index.html
    和 assets/*.css)。"""
    subprocess.run(
        [settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x00ff00:s={_W}x{_H}",
         "-frames:v", "1", str(tmp_path / "green.png")],
        check=True, timeout=60,
    )
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets" / "app.css").write_text("", encoding="utf-8")
    monkeypatch.setattr(settings, "frontend_dist", str(dist))
    return tmp_path


def _still_plan(subtitles: list[dict], position: str = "bottom"):
    return build_render_plan(
        sequence_id="s", revision=1, width=_W, height=_H, fps=30,
        clips=[{"id": "c", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "green.png"}},
        subtitle_clips=subtitles, subtitle_style={"bg_opacity": 0, "position": position},
    )


def _cue(cid: str, text: str, lane: int = 0) -> dict:
    return {"id": cid, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": text, "lane": lane}


def _two_tracks(position: str = "bottom"):
    return _still_plan([_cue("zh", _ORIGINAL, 0), _cue("en", _TRANSLATION, 1)], position)


def _one_track(text: str, position: str = "bottom"):
    return _still_plan([_cue("zh-en", text)], position)


def _frame(stage: Path, plan, name: str, *, png_path: bool, monkeypatch: pytest.MonkeyPatch) -> np.ndarray:
    monkeypatch.setattr(settings, "text_rasterize", png_path)
    out = render_still(plan, lambda key: stage / key, stage / f"{name}.png", 1.0)
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def _line_bands(frame: np.ndarray) -> list[dict]:
    """白色墨迹按行带切开:每一带 = 一行字,记它的上下沿(行)和左右沿(列)。"""
    ink = (frame[..., 0] > 200) & (frame[..., 2] > 200)
    rows = ink.any(axis=1)
    bands, start = [], None
    for y, hit in enumerate(rows):
        if hit and start is None:
            start = y
        if not hit and start is not None:
            bands.append((start, y - 1))
            start = None
    if start is not None:
        bands.append((start, len(rows) - 1))
    out = []
    for top, bottom in bands:
        cols = np.nonzero(ink[top : bottom + 1].any(axis=0))[0]
        out.append({"top": top, "bottom": bottom, "width": int(cols.max() - cols.min() + 1)})
    return out


def _assert_original_on_top(bands: list[dict]) -> None:
    assert len(bands) == 2, bands
    assert bands[0]["width"] < bands[1]["width"], f"上面那行应是原文(两个字,窄的那带):{bands}"


def _same_picture(stage: Path, png_path: bool, position: str, monkeypatch: pytest.MonkeyPatch) -> None:
    two = _frame(stage, _two_tracks(position), "two", png_path=png_path, monkeypatch=monkeypatch)
    one = _frame(stage, _one_track(f"{_ORIGINAL}\n{_TRANSLATION}", position), "one", png_path=png_path, monkeypatch=monkeypatch)
    differing = int((two != one).any(axis=-1).sum())
    assert differing == 0, f"分两条轨与一条轨两行的成片差 {differing} 个像素"
    _assert_original_on_top(_line_bands(two))


@needs_libass
@pytest.mark.parametrize("position", ["bottom", "top"])
def test_libass回落_分两条轨和一条轨写两行逐像素相同(stage: Path, position: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """此前第二道换到画面另一头:底部样式下两行相距八百多像素,与一条轨两行差 7228 个像素(顶部样式 7600)。"""
    _same_picture(stage, False, position, monkeypatch)


@needs_chromium
@pytest.mark.parametrize("position", ["bottom", "top"])
def test_png路_分两条轨和一条轨写两行逐像素相同(stage: Path, position: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """此前与一条轨两行差 14497 个像素(顶部样式 12591)。"""
    _same_picture(stage, True, position, monkeypatch)


#: libass 的行高就是 Fontsize(32 × 1.4 = 44.8px,见 render_executor._ASS_FONTSIZE_SCALE),预览 CSS 是
#: line-height 1.45(46.4px)—— 一条轨里写两行的字幕本来就差这 1.6px(取整后实测 2~3px)。叠放只要
#: 不在这之外再添差距。
_PITCH_TOLERANCE_PX = 3


@needs_libass
@needs_chromium
@pytest.mark.parametrize("position", ["bottom", "top"])
def test_libass回落与png路_顺序和行距一致_框贴着同一条边长(
    stage: Path, position: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    png = _line_bands(_frame(stage, _two_tracks(position), "two-png", png_path=True, monkeypatch=monkeypatch))
    ass = _line_bands(_frame(stage, _two_tracks(position), "two-ass", png_path=False, monkeypatch=monkeypatch))
    _assert_original_on_top(png)
    _assert_original_on_top(ass)

    png_pitch, ass_pitch = png[1]["top"] - png[0]["top"], ass[1]["top"] - ass[0]["top"]
    assert abs(png_pitch - ass_pitch) <= _PITCH_TOLERANCE_PX, (png, ass)

    # 贴边的那一行(底部样式是最后一行、顶部样式是第一行)两条路径的差,和只有一行字幕时一样:
    # 叠放没有把框挪离样式指定的那条边。单行时两条路径本来就差几个像素(libass 与 CSS 的基线不同)。
    single_png = _line_bands(_frame(stage, _one_track(_TRANSLATION, position), "one-png", png_path=True, monkeypatch=monkeypatch))
    single_ass = _line_bands(_frame(stage, _one_track(_TRANSLATION, position), "one-ass", png_path=False, monkeypatch=monkeypatch))
    anchored = -1 if position == "bottom" else 0
    edge = "bottom" if position == "bottom" else "top"
    single_gap = single_ass[0][edge] - single_png[0][edge]
    stacked_gap = ass[anchored][edge] - png[anchored][edge]
    assert abs(stacked_gap - single_gap) <= 1, (png, ass, single_png, single_ass)
