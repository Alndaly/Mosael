"""音频产出落盘:**扩展名要说对介质**。

素材库按扩展名判种类(media/probe.guess_kind:`.mp4` 就是视频)。而音乐接口交回的文件常常自带
一个容器名不副实的地址 —— 火山的歌曲文档原话是「默认 wav,但因转码可能是 mp4」。照抄扩展名的话,
一首歌会以「视频」进素材库:没有波形、时间线把它放上视频轨,生成页上它渲染成一块黑的播放器。

所以这里按**回包的 Content-Type 优先、地址后缀其次**挑扩展名,并且把「音频装在 mp4 容器里」
记成 `.m4a` —— 那就是这种文件的正名。几家音频 Adapter 共用这一处,而不是各自猜一遍。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from app.ai.media_transfer import download_to_path

_SUFFIX_BY_MIME = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/vnd.wave": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    # 音频装在 mp4 容器里 —— 正名是 m4a,见文件头。
    "video/mp4": ".m4a",
}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus"}
_SUFFIX_ALIASES = {".mp4": ".m4a", ".mpga": ".mp3"}


def audio_suffix(url: str, content_type: str, fallback: str = ".mp3") -> str:
    """这份音频该叫什么扩展名。回包说了就听回包的,没说看地址,都不认识用调用方给的兜底。"""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime in _SUFFIX_BY_MIME:
        return _SUFFIX_BY_MIME[mime]
    suffix = Path(urlparse(url or "").path).suffix.lower()
    suffix = _SUFFIX_ALIASES.get(suffix, suffix)
    return suffix if suffix in _AUDIO_SUFFIXES else fallback


def download_audio(url: str, output_dir: Path, *, stem: str = "generated", fallback: str = ".mp3", timeout: float = 300) -> Path:
    """把一条音频地址下载成本地文件,扩展名按上面的规矩定。地址多半只活 24 小时,所以立刻取。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    staged = output_dir / f"{stem}.download"
    content_type = download_to_path(url, staged, timeout=timeout)
    target = output_dir / f"{stem}{audio_suffix(url, content_type, fallback)}"
    staged.replace(target)
    return target

