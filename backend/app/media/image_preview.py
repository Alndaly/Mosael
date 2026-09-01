from __future__ import annotations

import mimetypes
import tempfile
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from app.core.child_process import run_logged
from app.core.config import settings

BROWSER_PREVIEW_NAME = "browser-preview.jpg"

# Electron/Chromium can put these straight in <img>. Everything else keeps its original bytes
# for download, but gets a derived JPEG for display and visual-model input. HEIC/HEIF is the
# important case: macOS can open it while Chromium cannot, so "it opens on this machine" is not
# evidence that the renderer can display it.
_BROWSER_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
_HEIF_SUFFIXES = {".heic", ".heif"}

# 系统 ffmpeg 的 codec 集合取决于发行版构建选项：二进制存在不代表能解 HEIC。注册随应用
# 打包的 libheif Pillow 插件，让开发机、Linux CI 和 Electron 安装包走同一条确定的解码路径。
register_heif_opener(thumbnails=False)


def browser_preview_path(asset_directory: Path) -> Path:
    return asset_directory / BROWSER_PREVIEW_NAME


def browser_compatible_image(source: Path, asset_directory: Path) -> tuple[Path, str] | None:
    """Return a browser-displayable image and its true MIME type.

    Browser-native inputs stay byte-for-byte original. Other image containers are decoded once
    into a full-size JPEG next to the asset. The derived file is also the single normalization
    seam for thumbnails and vision requests; otherwise a HEIC can be fixed in the chat bubble
    while still being sent to a provider mislabeled as JPEG.
    """
    if source.suffix.lower() in _BROWSER_IMAGE_SUFFIXES:
        mime = mimetypes.guess_type(source.name)[0] or "image/jpeg"
        return source, mime

    target = browser_preview_path(asset_directory)
    if target.is_file() and target.stat().st_size > 0:
        return target, "image/jpeg"

    # Keep a JPEG suffix on the temporary name so ffmpeg selects the correct muxer. Write then
    # replace: an interrupted conversion must not leave a zero-byte file that future requests
    # mistake for a valid cache entry.
    with tempfile.NamedTemporaryFile(
        prefix=".browser-preview-",
        suffix=".jpg",
        dir=asset_directory,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        if source.suffix.lower() in _HEIF_SUFFIXES:
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.save(temporary, format="JPEG", quality=92)
        else:
            run_logged(
                [
                    settings.ffmpeg,
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(temporary),
                ],
                check=True,
                capture_output=True,
                timeout=60,
                what="图片兼容预览生成",
            )
    except Exception:
        temporary.unlink(missing_ok=True)
        return None
    if not temporary.is_file() or temporary.stat().st_size <= 0:
        temporary.unlink(missing_ok=True)
        return None
    temporary.replace(target)
    return target, "image/jpeg"


__all__ = ["BROWSER_PREVIEW_NAME", "browser_compatible_image", "browser_preview_path"]
