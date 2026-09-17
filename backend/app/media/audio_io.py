"""把声音从素材里取出来、再放回去 —— 给"处理完要拿来听"的那几条路用(分离、降噪)。

和转写那条 `_extract_audio` 不是一回事:转写要 16 kHz 单声道,那是识别模型的输入格式;而分离、
降噪的产物是要进成片的,降到 16 kHz 单声道等于先把音质砍掉再去"修"它(ADR-0017 决定 6)。
所以这里**保留原采样率和声道数**,只换成无损的 PCM。
"""

from __future__ import annotations

from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.text import blame_line

#: 本来就是音频、可以直接交给引擎的扩展名。其余(视频)先抽一条出来。
AUDIO_SUFFIXES = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"})


class AudioIOError(RuntimeError):
    """取不出 / 放不回。message 可以直接给用户看。"""


def extract_audio(source: Path, target: Path) -> Path:
    """把 source 里的声音存成 target(wav,原采样率、原声道)。"""
    result = run_logged(
        [settings.ffmpeg, "-y", "-v", "error", "-i", str(source), "-vn", "-c:a", "pcm_s16le", "-f", "wav", str(target)],
        capture_output=True,
        text=True,
        timeout=900,
        what="抽取音轨",
    )
    if result.returncode != 0 or not target.is_file():
        raise AudioIOError(f"取不出这份素材的声音:{blame_line(result.stderr, fallback='ffmpeg 没有说明原因')}")
    return target


def as_audio(source: Path, work: Path) -> Path:
    """本来就是音频的原样用;视频先抽一条 wav 到 work 下。"""
    if source.suffix.lower() in AUDIO_SUFFIXES:
        return source
    return extract_audio(source, work / "source.wav")


def replace_audio(video: Path, audio: Path, target: Path) -> Path:
    """画面原样拷贝,声音换成 audio,写成一份**新**视频。

    画面不重新编码:降噪只动了声音,重编码画面只会白白掉画质、白白多等几分钟。
    """
    result = run_logged(
        [
            settings.ffmpeg, "-y", "-v", "error",
            "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            # 声音是从同一段视频里抽出来的,长度本来一致;-shortest 只是兜住编码器补的那几毫秒。
            "-shortest",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=900,
        what="替换音轨",
    )
    if result.returncode != 0 or not target.is_file():
        raise AudioIOError(f"没能把处理后的声音放回视频:{blame_line(result.stderr, fallback='ffmpeg 没有说明原因')}")
    return target
