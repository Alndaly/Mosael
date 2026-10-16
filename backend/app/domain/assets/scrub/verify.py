"""自证用的两条外部命令:**把音轨解成 PCM、把画面逐帧解出来**,各自算 MD5。

清元数据最怕的不是"没清干净",是"清的时候把画面或声音改坏了"。这两条是最后一道自证 ——
和输入比:画面逐帧 MD5 一样、音轨 PCM MD5 一样,才算真的只动了元数据。

**为什么单独一个模块**:`engine`(改)和 `gates`(验)都要用它,而它们互相不能再 import
(会成环,见 tests/test_import_layering)。这里是两者脚下的叶子。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings

#: 重封装 / 解码一份几分钟的片子是秒级到十几秒;超时给足,免得大文件被判成卡死。
FFMPEG_TIMEOUT = 3600


def run_ffmpeg(args: list[str], *, what: str, timeout: int = FFMPEG_TIMEOUT):
    """唯一的外部命令出口(`run_logged` 会给它记一行日志)。"""
    return run_logged(
        [settings.ffmpeg, "-hide_banner", "-nostdin", *args],
        check=True, capture_output=True, text=True, timeout=timeout, what=what, level=logging.DEBUG,
    )


def pcm_md5(path: Path) -> str:
    """把音轨**解码**成 PCM 再算 MD5 —— 证明清帧内元素没有动到声音。"""
    proc = run_ffmpeg(
        ["-v", "error", "-i", str(path), "-map", "0:a?", "-f", "md5", "-"],
        what="核对音轨", timeout=FFMPEG_TIMEOUT,
    )
    return (proc.stdout or "").strip()


def frame_md5(path: Path) -> str:
    """逐帧解码画面的 MD5(含帧序)—— 证明输出还是同一幅画面。"""
    proc = run_ffmpeg(
        ["-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "framemd5", "-"],
        what="核对画面", timeout=FFMPEG_TIMEOUT,
    )
    return "\n".join(line for line in (proc.stdout or "").splitlines() if not line.startswith("#"))


__all__ = ["FFMPEG_TIMEOUT", "frame_md5", "pcm_md5", "run_ffmpeg"]
