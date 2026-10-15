"""每镜两帧,拼成联系表。只读视频、写图片文件,不碰数据库。

- **两帧:15% 和 85% 处**(reelbench video-shots 的取法)。一帧看这一镜拍的是什么;两帧对照才看得出机位动没动 ——
  推镜头的两帧景别不同,摇镜头的两帧背景错开。都不取刀口附近:那里常有叠化、拖影。
- **联系表一张最多 25 镜**(5 × 5)。一次视觉调用交 A、B 两张:A 表全是 15% 的帧,B 表全是 85% 的帧,
  同一个格子是同一镜。格子左上角压镜号和时间码,模型回答时照着镜号说。
- **文字用 PIL 压,不用 ffmpeg 的 drawtext**:后者要 libfreetype,精简版 ffmpeg 没编进去。
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError

#: 一镜两帧落在镜内的哪儿。
FRAME_POINTS = {"a": 0.15, "b": 0.85}
#: 存下来的帧多宽:详情页的列表和联系表的格子都从它来,够看清景别和人物位置。
FRAME_WIDTH = 480
#: 一张联系表最多几镜,和排成几列。
SHEET_MAX = 25
SHEET_COLUMNS = 5
#: 联系表里一格多宽。5 列 × 320 = 1600 宽,视觉模型的常见上限以内。
TILE_WIDTH = 320
#: 同时跑几个 ffmpeg 取帧:取帧是解码一小段,并行几路就够,再多只是抢 CPU。
GRAB_WORKERS = 4


class ShotFramesError(LocalizedError, RuntimeError):
    """取帧或拼表失败。带文案 key(`shotsErr_*`)。"""


def frame_name(shot_id: str, point: str) -> str:
    return f"{shot_id}{point}.jpg"


def sheet_name(index: int, point: str) -> str:
    return f"sheet-{index:02d}{point}.jpg"


def frame_time(shot: dict[str, Any], point: str) -> float:
    return round(float(shot["start"]) + float(shot["seconds"]) * FRAME_POINTS[point], 3)


def _grab(source: Path, at: float, target: Path) -> None:
    #: `-ss` 放在 `-i` 前面:跳到最近的关键帧再往后解到那一刻(转码时 ffmpeg 默认精确 seek),
    #: 比放在后面从头解快得多 —— 一条片子要取上百帧。
    run_logged(
        [settings.ffmpeg, "-y", "-v", "error", "-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1",
         "-vf", f"scale='min({FRAME_WIDTH},iw)':-2", "-q:v", "4", str(target)],
        check=True, capture_output=True, timeout=120, what="取镜头帧",
    )


def grab_frames(source: Path, shots: list[dict[str, Any]], frames_dir: Path) -> None:
    """每镜两帧写进 `frames_dir`(S01a.jpg、S01b.jpg ……)。一帧取不到(片尾最后几帧解不出)不连坐,那一格留空。"""
    frames_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(frame_time(shot, point), frames_dir / frame_name(shot["id"], point))
            for shot in shots for point in FRAME_POINTS]

    def one(job: tuple[float, Path]) -> bool:
        at, target = job
        try:
            _grab(source, at, target)
        except (OSError, subprocess.SubprocessError):
            return False
        return target.is_file() and target.stat().st_size > 0

    with ThreadPoolExecutor(max_workers=GRAB_WORKERS) as pool:
        grabbed = list(pool.map(one, jobs))
    if jobs and not any(grabbed):
        raise ShotFramesError("shotsErr_noFrames")


def shot_label(shot: dict[str, Any]) -> str:
    """这一镜给人 / 模型看的标注:`S03 · 0:12.4–0:15.0`(ADR 0061 §3,分析抽帧每张图前压这个)。"""
    return f"{shot['id']} · {timecode(float(shot['start']))}–{timecode(float(shot['end']))}"


def grab_midframes(source: Path, shots: list[dict[str, Any]], max_frames: int) -> list[tuple[str, bytes]]:
    """按镜头取中点帧,返回 `(标注, JPEG 字节)`。每镜至少一帧;镜比上限多时均匀挑镜头。

    一帧取不到(片尾最后几帧解不出)不连坐,跳过那一镜;一帧都没取到抛 `ShotFramesError`,
    调用方据此回落均匀抽帧。"""
    if not shots:
        return []
    chosen = shots if len(shots) <= max_frames else [
        shots[round(index * (len(shots) - 1) / max(max_frames - 1, 1))]
        for index in range(max_frames)
    ]
    out: list[tuple[str, bytes]] = []
    with ThreadPoolExecutor(max_workers=GRAB_WORKERS) as pool:
        #: 取中点(不是联系表那 15% / 85%):分析要的是「这一镜的代表画面」,一个点就够。
        futures = {
            pool.submit(_grab_bytes, source, round(float(shot["start"]) + float(shot["seconds"]) * 0.5, 3)): shot
            for shot in chosen
        }
        for future, shot in futures.items():
            data = future.result()
            if data:
                out.append((shot_label(shot), data))
    if not out:
        raise ShotFramesError("shotsErr_noFrames")
    return out


def _grab_bytes(source: Path, at: float) -> bytes | None:
    """取一帧的 JPEG 字节;取不到回 None(不连坐)。"""
    with tempfile.TemporaryDirectory(prefix="mosael-shot-frame-") as tmp:
        target = Path(tmp) / "frame.jpg"
        try:
            _grab(source, at, target)
        except (OSError, subprocess.SubprocessError):
            return None
        return target.read_bytes() if target.is_file() and target.stat().st_size > 0 else None


def timecode(seconds: float) -> str:
    """0:12.4 / 1:02:03.5 —— 镜头常常不到一秒,十分之一秒要留着。"""
    tenths = int(round(max(0.0, seconds) * 10))
    whole, tenth = divmod(tenths, 10)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{tenth}"
    return f"{minutes}:{secs:02d}.{tenth}"


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 没有 FreeType 的 Pillow:只有位图字体,不能调字号
        return ImageFont.load_default()


def make_sheets(shots: list[dict[str, Any]], frames_dir: Path, sheets_dir: Path, aspect: float) -> list[dict[str, Any]]:
    """每 25 镜一组,各拼一张 A 表、一张 B 表。返回每张表覆盖哪几镜(`first` / `last` 是镜号)。"""
    sheets_dir.mkdir(parents=True, exist_ok=True)
    tile_height = max(90, min(TILE_WIDTH * 2, int(round(TILE_WIDTH / max(aspect, 0.2)))))
    font = _font(max(14, TILE_WIDTH // 16))
    made: list[dict[str, Any]] = []
    for index, first in enumerate(range(0, len(shots), SHEET_MAX), start=1):
        group = shots[first:first + SHEET_MAX]
        columns = min(SHEET_COLUMNS, len(group))
        rows = math.ceil(len(group) / columns)
        for point in FRAME_POINTS:
            sheet = Image.new("RGB", (columns * TILE_WIDTH, rows * tile_height), (24, 24, 24))
            draw = ImageDraw.Draw(sheet)
            for cell, shot in enumerate(group):
                x, y = (cell % columns) * TILE_WIDTH, (cell // columns) * tile_height
                frame = frames_dir / frame_name(shot["id"], point)
                if frame.is_file():
                    with Image.open(frame) as image:
                        tile = image.convert("RGB")
                        tile.thumbnail((TILE_WIDTH, tile_height))
                        sheet.paste(tile, (x + (TILE_WIDTH - tile.width) // 2, y + (tile_height - tile.height) // 2))
                label = f"{shot['id']} {timecode(frame_time(shot, point))}"
                box = draw.textbbox((0, 0), label, font=font)
                draw.rectangle((x, y, x + box[2] - box[0] + 12, y + box[3] - box[1] + 10), fill=(0, 0, 0))
                draw.text((x + 6 - box[0], y + 5 - box[1]), label, fill=(255, 220, 64), font=font)
                #: 格子之间一条细线,模型不会把相邻两镜看成一张图。
                draw.rectangle((x, y, x + TILE_WIDTH - 1, y + tile_height - 1), outline=(64, 64, 64))
            sheet.save(sheets_dir / sheet_name(index, point), "JPEG", quality=82)
        made.append({"index": index, "first": group[0]["id"], "last": group[-1]["id"],
                     "a": sheet_name(index, "a"), "b": sheet_name(index, "b")})
    return made


__all__ = ["FRAME_POINTS", "SHEET_MAX", "ShotFramesError", "frame_name", "frame_time", "grab_frames",
           "grab_midframes", "make_sheets", "sheet_name", "shot_label", "timecode"]
