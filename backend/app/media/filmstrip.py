from __future__ import annotations

import threading
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings
from app.media.probe import probe_media

"""
剪辑用的帧条:沿时间轴均匀取几帧,拼成**一张横向长图**,存在素材目录里(和缩略图、波形同一处)。

**为什么是一张图而不是几张。** 剪辑面板一打开就要看到整条片子的样子;分成 12 个请求的话,
它们会一格一格地跳出来,而且每一格都要过一次鉴权和落盘。拼成一张,浏览器一次拿完。

**为什么落盘缓存。** 抽帧要跑一次 ffmpeg,几百毫秒到几秒;而同一段素材会被反复打开剪辑面板。
和缩略图/波形/代理是同一个道理,也放在同一个地方 —— 素材删掉时它们一起走。

**为什么跳着取,不整段解码。** 此前用 `fps=12/时长` 让 ffmpeg 把整条片子解一遍、从里面挑 12 帧:4K HEVC 10-bit
约 0.3 秒 / 秒素材,6 分钟以上的片子就撞 120 秒超时 —— 而失败不记,画板每挂一次帧条就再解一遍,同一段素材的几个
请求各起一份 ffmpeg(MED-7)。现在每一格在输入端跳到那个时刻(`-ss` 放在 `-i` 前面:从最近的关键帧解起),一次
ffmpeg 里取 12 次,耗时跟片长无关;做不出来的记一个标记(连同源文件的大小和修改时间),源文件不变就不再重试;
同一段素材同时只有一个在做,后到的等它做完直接拿。
"""

FILMSTRIP_NAME = "filmstrip.jpg"
#: 做不出来的标记。内容是源文件的「大小:修改时间」—— 源文件换了(重新导入、修好了)就不算数。
FAILED_MARKER = "filmstrip.failed"
#: 取几帧。太少看不出片子的走向,太多每格就窄得认不出内容 —— 12 格在 420px 宽的面板上
#: 每格 35px,刚好还能认出画面。
FRAMES = 12
#: 每格的高度。宽度由原片比例定,不强行拉伸(拉伸过的画面反而更难认)。
FRAME_HEIGHT = 48
#: 跳着取,和片长无关;这个数只防一个卡死的解码器。
TIMEOUT_SECONDS = 60

#: 正在做帧条的素材目录 → 它的锁。同一段素材只做一次,不同素材互不等。
_making: dict[Path, threading.Lock] = {}
_making_guard = threading.Lock()


def filmstrip_path(asset_directory: Path) -> Path:
    return asset_directory / FILMSTRIP_NAME


def generate_filmstrip(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """尽力生成;失败就没有帧条 —— 剪辑面板照样能用(退回到只填秒数)。已经有了就直接给。"""
    if kind != "video":
        return None
    target = filmstrip_path(asset_directory)
    with _making_guard:
        lock = _making.setdefault(asset_directory, threading.Lock())
    with lock:
        if target.is_file():
            return target
        if _failed_before(source, asset_directory):
            return None
        made = _make(source, target)
        if made is None:
            _remember_failure(source, asset_directory)
        return made


def _make(source: Path, target: Path) -> Path | None:
    duration = _duration(source)
    if duration <= 0:
        return None
    inputs: list[str] = []
    for index in range(FRAMES):
        #: 每一格取它那一段的正中间:不会正好落在片尾之外(那样那一路没有帧,拼不出来)。
        inputs += ["-ss", f"{duration * (index + 0.5) / FRAMES:.3f}", "-i", str(source)]
    scaled = ";".join(f"[{index}:v:0]scale=-2:{FRAME_HEIGHT},setsar=1[f{index}]" for index in range(FRAMES))
    joined = "".join(f"[f{index}]" for index in range(FRAMES))
    args = [
        settings.ffmpeg, "-y", "-v", "error", *inputs,
        "-filter_complex", f"{scaled};{joined}hstack=inputs={FRAMES}[strip]",
        "-map", "[strip]", "-frames:v", "1", "-q:v", "4", str(target),
    ]
    try:
        run_logged(args, check=True, capture_output=True, timeout=TIMEOUT_SECONDS, what="帧条生成")
    except Exception:
        target.unlink(missing_ok=True)
        return None
    return target if target.exists() and target.stat().st_size > 0 else None


def _fingerprint(source: Path) -> str:
    stat = source.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _failed_before(source: Path, asset_directory: Path) -> bool:
    marker = asset_directory / FAILED_MARKER
    try:
        return marker.read_text(encoding="utf-8").strip() == _fingerprint(source)
    except OSError:
        return False


def _remember_failure(source: Path, asset_directory: Path) -> None:
    try:
        (asset_directory / FAILED_MARKER).write_text(_fingerprint(source), encoding="utf-8")
    except OSError:
        pass


def _duration(source: Path) -> float:
    # 走共用的探测:头里没写时长的录像(MediaRecorder 直录)这里曾读到 "N/A",帧条就没了。
    return float(probe_media(source).get("duration") or 0.0)
