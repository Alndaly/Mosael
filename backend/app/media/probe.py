from __future__ import annotations

import json
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.child_process import run_logged
import logging


AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma"}


#: 客户端说「我不知道这是什么」的那几种说法。**它们不是类型判断,不该压过扩展名。**
#:
#: 此前只写了 `content_type or 扩展名` —— 只要客户端给了任何字符串就不再看扩展名,而
#: `application/octet-stream` 恰恰是最常见的那一个:命令行工具、浏览器扩展、机器人和智能体
#: 工具上传时基本都发它(浏览器拖拽才会给出真类型)。后果是**一切图片都被当成视频**:
#: 一张 .png / .heic 进了「视频」筛选、按视频去放、时长空着还编出个 fps=1.0。
#: iPhone 照片默认就是 HEIC,这条路上进来的照片全中。
_UNKNOWN_MIMES = {"application/octet-stream", "binary/octet-stream", "application/unknown"}


def guess_kind(path: Path, content_type: str | None = None) -> str:
    if path.suffix.lower() in AUDIO_EXTENSIONS:
        return "audio"
    mime = (content_type or "").strip().lower()
    if not mime or mime in _UNKNOWN_MIMES:
        # 客户端没给或说不知道 —— 扩展名这时是唯一的线索,而它多半是对的。
        mime = mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    return "video"


def probe_media(path: Path, *, measure_missing_duration: bool = True) -> dict[str, Any]:
    """探出时长、画幅、帧率。

    时长先读容器头;头里没写(MediaRecorder 直录的 webm 就是这样),默认逐包量一遍
    (见 measure_duration)—— 「量不到」绝不能被调用处的 `or 0.0` 读成「0 秒」。
    `measure_missing_duration=False` 只给想知道「头里有没有」的人用(导入要据此决定补不补头)。
    """
    try:
        proc = run_logged(
            [
                settings.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height,r_frame_rate,avg_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20, what="媒体探测", level=logging.DEBUG)
    except Exception:
        return {}
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    info: dict[str, Any] = {}
    fmt = raw.get("format") or {}
    if fmt.get("duration") is not None:
        try:
            info["duration"] = float(fmt["duration"])
        except (TypeError, ValueError):
            pass
    if "duration" not in info and measure_missing_duration and raw.get("streams"):
        info["duration"] = measure_duration(path)
    for stream in raw.get("streams") or []:
        if stream.get("codec_type") == "video":
            info["width"] = stream.get("width")
            info["height"] = stream.get("height")
            info["fps"] = _frame_rate(path, stream, info.get("duration"))
            break
    return {k: v for k, v in info.items() if v is not None}


def measure_duration(path: Path) -> float | None:
    """容器头里没写时长时,把包逐个读一遍(只解封装、不解码),取最后一包的结束时刻。

    MediaRecorder 的 webm 是流式写出的,Chromium 不回填 Duration 头 —— 用户录了好几秒的
    参考音频,克隆那边量出来是「0.0 秒」。只读包头,几秒的录音是毫秒级,长片也只是读一遍文件。

    只有一包的不算一段:静态图片的头里同样没有时长,它那一包的「时长」是解封装器按 25fps
    给的默认值,不是它的长度。
    """
    try:
        proc = run_logged(
            [settings.ffprobe, "-v", "error", "-show_entries", "packet=pts_time,duration_time",
             "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True, timeout=120, what="媒体探测", level=logging.DEBUG,
        )
    except Exception:
        return None
    start: float | None = None
    end = 0.0
    packets = 0
    for line in proc.stdout.splitlines():
        # 带 side data 的包行尾会多一个逗号,只看前两列。
        fields = line.split(",")
        try:
            pts = float(fields[0])
        except ValueError:
            continue  # pts 为 N/A 的包定不了位置
        try:
            length = float(fields[1]) if len(fields) > 1 else 0.0
        except ValueError:
            length = 0.0
        start = pts if start is None else min(start, pts)
        end = max(end, pts + length)
        packets += 1
    if packets < 2 or start is None or end <= start:
        return None
    return round(end - start, 3)


#: 超过它的「帧率」不是帧率,是容器的时间单位。浏览器 MediaRecorder 录的 webm 以毫秒计时,
#: ffprobe 给出的 r_frame_rate / avg_frame_rate 都是 1000/1 —— 素材详情于是写着「1000fps」。
MAX_PLAUSIBLE_FPS = 240.0


def _frame_rate(path: Path, stream: dict[str, Any], duration: float | None) -> float | None:
    """标称帧率说得通就用它;说不通(是时间单位)就用平均帧率;还说不通就数帧:帧数 ÷ 时长。"""
    for key in ("r_frame_rate", "avg_frame_rate"):
        rate = _parse_rate(stream.get(key))
        if rate and rate <= MAX_PLAUSIBLE_FPS:
            return rate
    if not duration:
        return None
    try:
        proc = run_logged(
            [settings.ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets",
             "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True, timeout=60, what="媒体探测", level=logging.DEBUG,
        )
        frames = int(proc.stdout.strip().split(",")[0])
    except Exception:
        return None
    return round(frames / duration, 3) if frames > 0 else None


def remux_in_place(path: Path) -> bool:
    """Lossless remux (`-c copy`) that rewrites the container header in place.

    MediaRecorder 直录的 webm 是流式写出的,Chromium 不回填 Duration 头,
    ffprobe 探不到时长、按时长定位的操作全部失灵。整文件无损重封装一遍,
    由 ffmpeg 写出完整的头,再重探即可。失败时保留原文件。

    .webm 后缀会推导出只收 VP8/VP9/AV1 的严格 WebM muxer;装着别的编码的
    "webm" 文件(改过扩展名等)换通用 matroska muxer 再试一次。"""
    tmp = path.with_name(path.stem + ".remux" + path.suffix)
    attempts: list[list[str]] = [[]]
    if path.suffix.lower() in {".webm", ".mkv"}:
        attempts.append(["-f", "matroska"])
    for extra in attempts:
        try:
            run_logged(
                [settings.ffmpeg, "-y", "-v", "error", "-i", str(path), "-c", "copy", *extra, str(tmp)],
                check=True,
                capture_output=True,
                timeout=120, what="音轨探测", level=logging.DEBUG)
        except Exception:
            tmp.unlink(missing_ok=True)
            continue
        if tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(path)
            return True
        tmp.unlink(missing_ok=True)
    return False


#: 在浏览器里拖不动的容器。QuickTime(Mac 录屏、iPhone 视频)的数据排布让 Chromium 每次跳转
#: 都在文件里来回跳读、发出上百个中途放弃的按范围请求:一条 370MB 的录屏单次跳转 0.06–2.4 秒,
#: 同样的画面和声音换成 mp4 容器(不重编码)只要 0.03–0.17 秒(实测,同一台机器同一个服务)。
REPACKAGED_SUFFIXES = frozenset({".mov", ".qt"})


def repackage_as_mp4(path: Path) -> Path | None:
    """把 .mov 里的画面和声音**原样**搬进同名 .mp4(`-c copy`,不重编码,画质不变),删掉 .mov。

    返回新路径;不是这类容器、或编码放不进 mp4(ProRes、PCM 音轨之类)就返回 None,原文件不动。
    时间码、章节这类数据轨不搬 —— mp4 装不下,界面也用不到。
    """
    if path.suffix.lower() not in REPACKAGED_SUFFIXES:
        return None
    target = path.with_suffix(".mp4")
    partial = path.with_name(path.stem + ".repackage.mp4")
    try:
        codec = run_logged(
            [settings.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
             "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True, timeout=30, what="容器重封装", level=logging.DEBUG,
        ).stdout.strip()
        # HEVC 进 mp4 要标成 hvc1,Chromium/Safari 才认;H.264 等不需要。
        tag = ["-tag:v", "hvc1"] if codec == "hevc" else []
        run_logged(
            [settings.ffmpeg, "-y", "-v", "error", "-i", str(path), "-map", "0:v", "-map", "0:a?", "-c", "copy",
             *tag, "-movflags", "+faststart", str(partial)],
            check=True, capture_output=True, timeout=600, what="容器重封装", level=logging.DEBUG,
        )
    except Exception:
        partial.unlink(missing_ok=True)
        return None
    if not partial.is_file() or partial.stat().st_size == 0:
        partial.unlink(missing_ok=True)
        return None
    partial.replace(target)
    path.unlink(missing_ok=True)
    return target


# ffprobe is cheap but not free; a long timeline should not fork one per source at once.
_MAX_PARALLEL_PROBES = 8


def probe_has_audio(path: Path) -> bool:
    try:
        proc = run_logged(
            [settings.ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20, what="封面提取", level=logging.DEBUG)
    except Exception:
        return False
    return bool(proc.stdout.strip())


def probe_has_audio_many(paths: "Iterable[Path]") -> dict[Path, bool]:
    """probe_has_audio over many files at once.

    Building an ffmpeg command probes every optional source to find out whether it carries an
    audio stream, and each probe spawns ffprobe and waits ~30-80ms. Done in series that is a
    second or more of dead time before the render even starts, for work that is pure waiting on
    child processes — so it runs concurrently, bounded so a long timeline cannot fork hundreds
    of ffprobes at once. Deduped: the same source used by several clips is probed once.
    """
    unique = list(dict.fromkeys(paths))
    if not unique:
        return {}
    if len(unique) == 1:
        return {unique[0]: probe_has_audio(unique[0])}
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL_PROBES, len(unique))) as pool:
        return dict(zip(unique, pool.map(probe_has_audio, unique)))


def _parse_rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        a, b = value.split("/", 1)
        try:
            denom = float(b)
            return float(a) / denom if denom else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None

