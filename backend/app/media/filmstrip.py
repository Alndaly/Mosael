from __future__ import annotations

from pathlib import Path

from app.core.child_process import run_logged

"""
剪辑用的帧条:沿时间轴均匀取几帧,拼成**一张横向长图**,存在素材目录里(和缩略图、波形同一处)。

**为什么是一张图而不是几张。** 剪辑面板一打开就要看到整条片子的样子;分成 12 个请求的话,
它们会一格一格地跳出来,而且每一格都要过一次鉴权和落盘。拼成一张,浏览器一次拿完。

**为什么落盘缓存。** 抽帧要跑一次 ffmpeg,几百毫秒到几秒;而同一段素材会被反复打开剪辑面板。
和缩略图/波形/代理是同一个道理,也放在同一个地方 —— 素材删掉时它们一起走。
"""

FILMSTRIP_NAME = "filmstrip.jpg"
#: 取几帧。太少看不出片子的走向,太多每格就窄得认不出内容 —— 12 格在 420px 宽的面板上
#: 每格 35px,刚好还能认出画面。
FRAMES = 12
#: 每格的高度。宽度由原片比例定,不强行拉伸(拉伸过的画面反而更难认)。
FRAME_HEIGHT = 48


def filmstrip_path(asset_directory: Path) -> Path:
    return asset_directory / FILMSTRIP_NAME


def generate_filmstrip(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """尽力生成;失败就没有帧条 —— 剪辑面板照样能用(退回到只填秒数)。"""
    if kind != "video":
        return None
    target = filmstrip_path(asset_directory)
    duration = _duration(source)
    if duration <= 0:
        return None
    #: fps 设成「整条片子取 FRAMES 帧」。tile 把它们横着拼成一张。
    #: round=up 是为了短片:算下来不足一帧时至少也取到一帧,否则 tile 会得到空图。
    args = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-vf", f"fps={FRAMES / duration}:round=up,scale=-2:{FRAME_HEIGHT},tile={FRAMES}x1",
        "-frames:v", "1", "-q:v", "4", str(target),
    ]
    try:
        run_logged(args, check=True, capture_output=True, timeout=120, what="帧条生成")
    except Exception:
        return None
    return target if target.exists() and target.stat().st_size > 0 else None


def _duration(source: Path) -> float:
    try:
        probe = run_logged(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(source)],
            check=True, capture_output=True, text=True, timeout=20, what="帧条探测",
        )
        return float(probe.stdout.strip() or 0)
    except Exception:
        return 0.0
