"""进程内的暂存目录:生成时下回来的成片、插件交回的产物,登记进素材库之前先落在这里。

**放在数据目录里(`<数据目录>/tmp/<用途>/`),不放系统临时目录。** 用的人在 `finally` 里删它,可任务线程是 daemon ——
进程被杀、`--reload` 重启时 `finally` 不执行。此前生成一段大视频中途重启一次,系统临时目录里就留下几百 MB 的
`mosael-gen-*` 和下到一半的 `.part`,没人收(Windows 的 %TEMP% 不会自己清);接着取的时候又另建一个目录再下一遍。
放在这里,下次启动由 `clear_scratch` 清掉;顺带和素材库在同一块盘上。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

#: 生成运行器下回来的成片(见 domain/generation/runner)。
GENERATION = "gen"
#: 插件交回的产物(见 domain/plugins/artifacts)。
PLUGIN_OUTPUT = "plugin-out"


def scratch_root() -> Path:
    return settings.data_dir / "tmp"


def scratch_dir(purpose: str) -> Path:
    """新建一个只给这一次用的暂存目录。用完由调用方删;进程中途没了的,下次启动清。"""
    parent = scratch_root() / purpose
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=parent))


def clear_scratch(*, older_than: float) -> int:
    """清掉修改时间早于 `older_than`(时间戳)的暂存条目 —— 上一个进程留下的。返回清掉了几项。

    启动时、在任何任务起来之前调:那时这里的一切都是上一个进程的。按时间判而不是全删,是为了万一被晚调用,
    也不会删掉这一个进程刚建的目录。"""
    root = scratch_root()
    if not root.is_dir():
        return 0
    cleared = 0
    for purpose in root.iterdir():
        if not purpose.is_dir() or purpose.is_symlink():
            continue
        for entry in purpose.iterdir():
            try:
                if entry.lstat().st_mtime >= older_than:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                cleared += 1
            except OSError:
                logger.warning("没能清掉上一次留下的暂存 %s", entry, exc_info=True)
    return cleared
