"""这台机器用哪个 ffmpeg,以及带字的导出烧得了字没有(ADR 0048 第一步)。

- **存**:「管理 → 引擎 → FFmpeg」里填的路径存在单例 MediaToolsConfig(空 = PATH 上的 `ffmpeg`)。发布版的后端从 Finder 起,
  读不到 shell rc 里的环境变量,「设 MOSAEL_FFMPEG」在那里做不到 —— 这一格就是给它的。填的是这台机器上要执行的程序,
  所以只有部署管理员能改(路由把关)。
- **推**:起 ffmpeg 的地方一律读 `settings.ffmpeg` / `settings.ffprobe`(tests/test_ffmpeg_comes_from_settings 钉着),
  所以生效的那份写回这两项:启动时一次、保存提交之后一次,和重试次数(domain/ai_runtime)同一套做法。
  环境变量 MOSAEL_FFMPEG 给了的话以它为准,这一格整个不生效 —— 开发、测试、容器部署靠它钉死 ffmpeg;界面上照实说。
- **ffprobe 跟着走**:填的 ffmpeg 旁边有 ffprobe 就一起用(各家发行版都把两个放在同一个目录);没有就还用 PATH 上的。
  MOSAEL_FFPROBE 给了的话 ffprobe 听它的。
- **探**:找不找得到、什么版本、有没有 libass、带字的导出走哪条路。启动时在后台探一次,保存后、点「重新检测」时再探,
  结果给管理页显示。此前只记一行日志,用户看不见,要等带字幕的导出被拒才知道。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.child_process import run_logged
from app.core.config import FFMPEG_FIELDS_FROM_ENVIRONMENT, Settings, settings
from app.core.i18n import LocalizedError
from app.core.unit_of_work import after_commit
from app.db.models import MediaToolsConfig

logger = logging.getLogger(__name__)

SINGLETON_ID = "default"
DEFAULT_FFMPEG: str = Settings.model_fields["ffmpeg"].default
DEFAULT_FFPROBE: str = Settings.model_fields["ffprobe"].default


class FfmpegPathError(LocalizedError):
    """填的路径用不了。key 说是哪一种(`ffmpegPath_*`)。"""


@dataclass(frozen=True)
class FfmpegStatus:
    #: 探的是哪一个 —— 生效的那份(`settings.ffmpeg`),可能只是程序名。
    ffmpeg: str
    #: 它实际在哪(程序名按 PATH 找到的那个文件):界面上给人看的是这个 —— 「ffmpeg」说明不了是不是 Homebrew 那个。找不到时同上。
    location: str
    found: bool
    #: 「9.0.2」这类;没找到为空。
    version: str
    libass: bool
    #: 带字幕 / 花字 / AI 标识的导出走哪条路:'browser'、'libass';None = 两条都不通,这类导出在建任务之前就会被拒。
    text_burn_in: str | None


def pinned_by_environment() -> bool:
    """MOSAEL_FFMPEG 给了:这一格不生效。"""
    return "ffmpeg" in FFMPEG_FIELDS_FROM_ENVIRONMENT


def saved_path(db: Session) -> str:
    row = db.get(MediaToolsConfig, SINGLETON_ID)
    return row.ffmpeg_path if row is not None else ""


def save_path(db: Session, raw: str) -> str:
    """存下来,**提交之后**对本进程生效并重探一次。填的不是一个能跑的 ffmpeg 就抛 FfmpegPathError,什么都不存。"""
    path = _checked(raw)
    row = db.get(MediaToolsConfig, SINGLETON_ID)
    if row is None:
        row = MediaToolsConfig(id=SINGLETON_ID)
        db.add(row)
    row.ffmpeg_path = path

    def take_effect() -> None:
        apply(path)
        recheck()

    after_commit(db, take_effect)
    return path


def effective_binaries(path: str) -> tuple[str, str]:
    """填的这一格换算成 (ffmpeg, ffprobe)。不看环境变量 —— 那一层在 apply 里。"""
    if not path:
        return DEFAULT_FFMPEG, DEFAULT_FFPROBE
    return path, _sibling_ffprobe(path) or DEFAULT_FFPROBE


def apply(path: str) -> None:
    if pinned_by_environment():
        return
    ffmpeg, ffprobe = effective_binaries(path)
    settings.ffmpeg = ffmpeg
    if "ffprobe" not in FFMPEG_FIELDS_FROM_ENVIRONMENT:
        settings.ffprobe = ffprobe


def apply_to_process(db: Session) -> None:
    """启动时把库里那份推进进程。存着的路径后来不在了(卸掉了、换了机器)照样推:探测会说找不到,界面上看得见。"""
    apply(saved_path(db))


_status: FfmpegStatus | None = None
_status_lock = threading.Lock()


def status() -> FfmpegStatus:
    """上一次探的结果;生效的 ffmpeg 换过(或还没探过)就现探。"""
    current = _status
    if current is not None and current.ffmpeg == settings.ffmpeg:
        return current
    return recheck()


def recheck() -> FfmpegStatus:
    """重探一次(装了 / 换了 ffmpeg 之后)。libass 的探测按路径缓存着,同一个路径上换了程序也要重探,所以先清掉。"""
    global _status
    from app.media.render_executor import ffmpeg_has_libass, text_burn_path

    with _status_lock:
        ffmpeg = settings.ffmpeg
        ffmpeg_has_libass.cache_clear()
        version = _version(ffmpeg)
        found = version is not None
        libass = found and ffmpeg_has_libass(ffmpeg)
        result = FfmpegStatus(ffmpeg=ffmpeg, location=shutil.which(ffmpeg) or ffmpeg, found=found,
                              version=version or "", libass=libass, text_burn_in=text_burn_path())
        _status = result
    if not result.found:
        logger.warning("ffmpeg %s not found: export, thumbnails and transcription need it", ffmpeg)
    elif result.text_burn_in is None:
        logger.warning("ffmpeg %s has no libass and the browser text path is unavailable: "
                       "exports with subtitles or titles will be refused", ffmpeg)
    return result


def _version(ffmpeg: str) -> str | None:
    """`ffmpeg -version` 第一行里的版本号;跑不起来、或者说的不是 ffmpeg,返回 None。"""
    try:
        proc = run_logged([ffmpeg, "-hide_banner", "-version"], capture_output=True, text=True,
                          timeout=20, what="ffmpeg 探测", level=logging.DEBUG)
    except (OSError, subprocess.SubprocessError):
        return None
    first = (proc.stdout or "").splitlines()[:1]
    words = first[0].split() if first else []
    if proc.returncode != 0 or len(words) < 3 or " ".join(words[:2]) != "ffmpeg version":
        return None
    return words[2]


def _sibling_ffprobe(ffmpeg: str) -> str | None:
    candidate = Path(ffmpeg).with_name("ffprobe" + Path(ffmpeg).suffix)
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _checked(raw: str) -> str:
    """空 = 用 PATH 上的;否则要是一个能跑的 ffmpeg 的绝对路径。"""
    text = (raw or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise FfmpegPathError("ffmpegPath_notAbsolute", path=text)
    if not path.is_file():
        raise FfmpegPathError("ffmpegPath_missing", path=str(path))
    if not os.access(path, os.X_OK):
        raise FfmpegPathError("ffmpegPath_notExecutable", path=str(path))
    if _version(str(path)) is None:
        raise FfmpegPathError("ffmpegPath_notFfmpeg", path=str(path))
    return str(path)
