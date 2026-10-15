"""拆镜头之「帧」那一半(domain/shots/frames.py):15% / 85% 两帧、联系表 ≤25 镜、格角压字。

联系表是纯 PIL 的活:造假的帧文件(不跑 ffmpeg)就能验拼表、分张、压字。
取帧(grab_frames)要解码视频,用 ffmpeg 现造一条小片子验。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.domain.shots import frames

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _shot(index: int, start: float, end: float) -> dict:
    return {"id": frames_name_id(index), "start": start, "end": end, "seconds": round(end - start, 3)}


def frames_name_id(index: int) -> str:
    from app.domain.shots.detect import shot_id

    return shot_id(index)


def _write_frame(frames_dir: Path, shot_id: str, point: str, color: tuple[int, int, int] = (80, 120, 160)) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (480, 270), color).save(frames_dir / frames.frame_name(shot_id, point), "JPEG")


# --------------------------------------------------------------------------------------
# 时间点
# --------------------------------------------------------------------------------------

def test_frame_time_at_15_and_85_percent() -> None:
    shot = {"id": "S03", "start": 12.0, "seconds": 3.0, "end": 15.0}
    assert frames.frame_time(shot, "a") == pytest.approx(12.45)
    assert frames.frame_time(shot, "b") == pytest.approx(14.55)


def test_timecode_keeps_tenths() -> None:
    assert frames.timecode(12.4) == "0:12.4"
    assert frames.timecode(62.06) == "1:02.1"  # 四舍五入到十分之一秒
    assert frames.timecode(3600.0) == "1:00:00.0"
    assert frames.timecode(0.0) == "0:00.0"


# --------------------------------------------------------------------------------------
# 联系表(纯 PIL,不跑 ffmpeg)
# --------------------------------------------------------------------------------------

def test_make_sheets_splits_into_groups_of_25(tmp_path: Path) -> None:
    shots = [_shot(i, float(i), float(i) + 2.0) for i in range(1, 31)]
    for shot in shots:
        for point in frames.FRAME_POINTS:
            _write_frame(tmp_path / "frames", shot["id"], point)
    made = frames.make_sheets(shots, tmp_path / "frames", tmp_path / "sheets", 16 / 9)
    assert [sheet["index"] for sheet in made] == [1, 2]
    assert made[0]["first"] == "S01" and made[0]["last"] == "S25"
    assert made[1]["first"] == "S26" and made[1]["last"] == "S30"
    for sheet in made:
        for name in (sheet["a"], sheet["b"]):
            assert (tmp_path / "sheets" / name).is_file()


def test_sheet_has_five_columns_and_label_corner(tmp_path: Path) -> None:
    shots = [_shot(i, float(i), float(i) + 2.0) for i in range(1, 6)]
    for shot in shots:
        for point in frames.FRAME_POINTS:
            _write_frame(tmp_path / "frames", shot["id"], point, color=(200, 60, 60))
    (made,) = frames.make_sheets(shots, tmp_path / "frames", tmp_path / "sheets", 16 / 9)
    with Image.open(tmp_path / "sheets" / made["a"]) as sheet:
        assert sheet.width == 5 * frames.TILE_WIDTH
        #: 格角压了字:左上角那块不该是纯色背景(背景是 24,24,24,帧是 200,60,60,字是 255,220,64)。
        corner = sheet.convert("RGB").crop((4, 4, 90, 30))
        colors = set(corner.getdata())
        assert len(colors) > 2, "格角没压上镜号 / 时间码"
        #: 格子之间画了细线:相邻两格交界比格内的帧明显暗(JPEG 压缩后取不到精确色,看明暗)。
        #: 取格子中下部(避开格角那块压字黑底),帧是 200,60,60,分隔线是 64,64,64。
        seam_x = frames.TILE_WIDTH
        seam = [sheet.convert("RGB").getpixel((seam_x, y)) for y in range(60, 90)]
        inside = [sheet.convert("RGB").getpixel((seam_x - 14, y)) for y in range(60, 90)]
        assert sum(sum(p) for p in seam) / len(seam) < sum(sum(p) for p in inside) / len(inside) * 0.7


def test_sheet_tiles_at_most_25_and_names_files(tmp_path: Path) -> None:
    assert frames.SHEET_MAX == 25
    assert frames.sheet_name(2, "a") == "sheet-02a.jpg"
    assert frames.frame_name("S07", "b") == "S07b.jpg"


def test_make_sheets_survives_a_missing_frame(tmp_path: Path) -> None:
    shots = [_shot(i, float(i), float(i) + 2.0) for i in range(1, 4)]
    for shot in shots[:2]:  # 第三镜的帧「取不到」:格子留空,表照样出
        for point in frames.FRAME_POINTS:
            _write_frame(tmp_path / "frames", shot["id"], point)
    (made,) = frames.make_sheets(shots, tmp_path / "frames", tmp_path / "sheets", 16 / 9)
    assert (tmp_path / "sheets" / made["b"]).is_file()


# --------------------------------------------------------------------------------------
# 取帧(真跑 ffmpeg)
# --------------------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_grab_frames_two_per_shot(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, timeout=60,
    )
    shots = [{"id": "S01", "start": 0.0, "seconds": 2.0, "end": 2.0}]
    frames.grab_frames(video, shots, tmp_path / "frames")
    for point in frames.FRAME_POINTS:
        grabbed = tmp_path / "frames" / frames.frame_name("S01", point)
        assert grabbed.is_file() and grabbed.stat().st_size > 0
        with Image.open(grabbed) as image:
            assert image.width <= frames.FRAME_WIDTH


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_grab_frames_all_failing_raises(tmp_path: Path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, timeout=60,
    )
    #: 取帧点全在视频末尾之后 → 全败 → 报 shotsErr_noFrames。
    shots = [{"id": "S01", "start": 50.0, "seconds": 2.0, "end": 52.0}]
    with pytest.raises(frames.ShotFramesError) as err:
        frames.grab_frames(video, shots, tmp_path / "frames")
    assert err.value.key == "shotsErr_noFrames"
