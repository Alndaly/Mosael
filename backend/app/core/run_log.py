"""把一次失败的**完整输出**写到盘上。

界面上那句话只能有一句(见 core/text.blame_line),而排查要的是全文。此前全文哪儿都没有:
`run_logged` 的失败日志只留 800 字符,报错消息只留几百字 —— 于是真机上的失败除了让用户
重跑一遍并录屏之外无法诊断。装引擎依赖那条路先补上了落盘,而下载权重那条路仍然没有,
同一件事的第二处。所以提到这里,谁都能用。

写不下(只读盘、权限)就返回 None:落不了盘是件小事,不该让它把正在报的那个错盖掉。
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

#: 每一类各留最近这么多份。一份几十 KB,留太多是往用户的数据目录里堆垃圾;
#: 而只留一份的话,「上次成功、这次失败,差在哪」就没得比。
KEEP = 20


def logs_dir() -> Path:
    return settings.data_dir / "logs"


def save(text: str, *, kind: str, what: str) -> Path | None:
    """写一份完整输出,返回它的路径。`kind` 是文件名前缀(pip / worker),用于分类保留。"""
    try:
        directory = logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", what).strip("-") or kind
        path = directory / f"{kind}-{slug}-{time.strftime('%Y%m%d-%H%M%S')}.log"
        path.write_text(text, encoding="utf-8")
        _prune(directory, kind)
        return path
    except OSError:
        logger.warning("写 %s 日志失败", kind, exc_info=True)
        return None


def _prune(directory: Path, kind: str) -> None:
    try:
        files = sorted(directory.glob(f"{kind}-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[KEEP:]:
            stale.unlink(missing_ok=True)
    except OSError:  # 清理失败不该让别的事失败 —— 它只是在打扫
        logger.debug("清理 %s 日志失败", kind, exc_info=True)
