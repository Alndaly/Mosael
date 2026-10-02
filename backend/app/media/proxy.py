"""Proxies for the WebCodecs compositor.

On video import we transcode a lightweight 720p H.264 proxy with a fixed short
GOP + faststart. The browser compositor decodes THIS (guaranteed-decodable
avc/mp4, cheap to seek) instead of the original, whose codec/container could be
anything. Best-effort — a failed proxy just means that clip falls back to the
`<video>` element path in the preview.

The same pipeline, minus the height cap and at a near-lossless CRF, produces the
**export proxy**: a full-resolution short-GOP variant the offline export
compositor decodes so a single canvas renderer drives both preview and export
(see docs/superpowers/specs/2026-07-27-preview-export-parity-design.md, 路 C).
Built on demand at export time and cache-reused; it is an intermediate that the
final encode re-compresses, hence the low CRF to keep generational loss negligible.

**Audio proxy** (`audio_proxy.m4a`): every sound-bearing asset (video or audio) also gets a small
AAC-LC 48 kHz stereo file. The preview mixer used to fetch the *original* and `decodeAudioData` the
whole thing — an hour-long WAV is hundreds of MB to download and ~1.4 GB of decoded PCM. The
proxy is ~10× smaller on the wire, faststart (the sample table comes first), so the browser reads
the index with a few Range requests and decodes only the stretch of samples it is about to play.

**这个模块只会转码。** 「什么时候该转、转完算不算一次任务成功、素材的状态怎么改」都不在这里
—— 那是业务决策,住在 `domain/assets/proxies.py`。此前它们挤在一起,于是 media 这个适配器
反过来 import 了 domain.jobs:一个只该会干活的层认识了业务,`media` 也就没法脱离任务系统
单独用(想在一个离线脚本里只调 build_proxy,会把 DB 会话和事件总线一起拖进来)。
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings

PROXY_NAME = "proxy.mp4"
# Height cap for the proxy. The compositor decodes this, not the original, so a
# 720p ceiling keeps decode cheap while staying crisp on typical preview panes.
PROXY_HEIGHT = 720
# Full-resolution export proxy (路 C): same short-GOP/no-B-frame recipe, native resolution, and a
# near-visually-lossless CRF because the final export pass re-encodes it — the extra generation must
# not show. Sibling to the asset like the preview proxy; larger, but temporary and cache-reused.
# Bound concurrent ffmpeg transcodes (a startup backfill can queue one job per video at once).
TRANSCODE_SLOTS = threading.Semaphore(2)

AUDIO_PROXY_NAME = "audio_proxy.m4a"
# 48 kHz 是预览 AudioContext 的常见采样率:解出来不用再重采样。立体声保住声像(配乐、空间感),
# 96 kbps 的 AAC-LC 对监听足够,一小时约 43 MB。
AUDIO_PROXY_SAMPLE_RATE = 48_000
AUDIO_PROXY_BITRATE = "96k"


def proxy_path(asset_directory: Path) -> Path:
    return asset_directory / PROXY_NAME


def build_proxy(source: Path, target: Path) -> bool:
    """Transcode the H.264 short-GOP faststart preview proxy. Returns success."""
    # Cap height (even width via -2), never upscaling — yuv420p needs even dimensions either way.
    scale = f"scale=-2:'min({PROXY_HEIGHT},ih)'"
    args = [
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(source),
        "-vf", scale,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        # Fixed 30-frame GOP (a keyframe every 30 frames, no scene-cut keyframes)
        # → the compositor can seek to a nearby sync sample cheaply.
        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        # No B-frames: decode order == presentation order (cts == dts), so the
        # WebCodecs compositor never has to reorder frames — seeking is trivial.
        "-bf", "0",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        str(target),
    ]
    try:
        run_logged(args, check=True, capture_output=True, timeout=600, what="代理转码")
    except Exception:
        target.unlink(missing_ok=True)
        return False
    return target.is_file()


def audio_proxy_path(asset_directory: Path) -> Path:
    return asset_directory / AUDIO_PROXY_NAME


def build_audio_proxy(source: Path, target: Path) -> bool:
    """Transcode the preview audio proxy (first audio stream only). Returns success.

    Callers check `probe_has_audio` first: a source with no audio stream is not a failure, it is
    a silent asset, and must be recorded as such rather than retried.
    """
    args = [
        settings.ffmpeg, "-y", "-v", "error",
        "-i", str(source),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", "2", "-ar", str(AUDIO_PROXY_SAMPLE_RATE),
        "-c:a", "aac", "-b:a", AUDIO_PROXY_BITRATE,
        # moov first: the browser reads the sample table with a couple of small Range requests
        # and then fetches only the byte ranges of the samples it is about to decode.
        "-movflags", "+faststart",
        str(target),
    ]
    try:
        run_logged(args, check=True, capture_output=True, timeout=1800, what="音频代理转码")
    except Exception:
        target.unlink(missing_ok=True)
        return False
    return target.is_file()


__all__ = [
    "AUDIO_PROXY_NAME", "PROXY_NAME", "PROXY_HEIGHT", "TRANSCODE_SLOTS",
    "audio_proxy_path", "build_audio_proxy", "build_proxy", "proxy_path",
]
