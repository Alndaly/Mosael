from __future__ import annotations

import logging
import tempfile

logger = logging.getLogger(__name__)
from pathlib import Path
from typing import IO

from PIL import Image, ImageOps

from app.core.child_process import run_logged
from app.core.config import settings
from app.media.image_preview import browser_compatible_image

#: WebP 而不是 JPEG:**JPEG 没有透明通道**。带透明的 PNG(图标、抠图)转成 JPEG 时透明像素
#: 里残留的颜色全露出来 —— 四角一块黑、边缘一圈白色毛刺,而原图明明是透明的。
THUMBNAIL_NAME = "thumbnail.webp"
THUMBNAIL_MEDIA_TYPE = "image/webp"
THUMBNAIL_WIDTH = 320


def thumbnail_path(asset_directory: Path) -> Path:
    return asset_directory / THUMBNAIL_NAME


def write_thumbnail(image: Image.Image, target: Path | IO[bytes], *, width: int = THUMBNAIL_WIDTH, height: int | None = None) -> None:
    """等比缩小到宽不超过 `width`(给了 `height` 时高也不超过它),不放大;写成 WebP,有透明就留着透明。"""
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in {"RGBA", "LA", "PA"} or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    scale = min(1.0, width / image.width, height / image.height if height else 1.0)
    if scale < 1:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.Resampling.LANCZOS)
    image.save(target, "WEBP", quality=82, method=4)


def generate_thumbnail(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """Best-effort thumbnail extraction; import must never fail because of it."""
    #: 文档的封面是解析时渲的第一页(ADR 0031),不在导入这一步用 ffmpeg 取帧。
    if kind in ("audio", "document"):
        return None
    target = thumbnail_path(asset_directory)
    if kind == "image":
        compatible = browser_compatible_image(source, asset_directory)
        if compatible is None:
            return None
        try:
            with Image.open(compatible[0]) as image:
                write_thumbnail(image, target)
        except Exception as exc:
            #: 不上抛是对的(导入不该因缩略图失败而失败),但失败要去日志 ——
            #: 不然损坏的图每次被访问都静默重试、静默失败,谁也看不见。
            logger.warning("缩略图没生成(素材 %s): %s", asset_directory.name, exc)
            return None
        return target if target.is_file() and target.stat().st_size > 0 else None
    # 视频:ffmpeg 取一帧成 PNG,再走同一个写法。0.5s 跳过片头黑场;超短片段 seek 会落在
    # 片尾之后取不到帧,退回首帧再试。
    with tempfile.TemporaryDirectory(prefix="mosael-thumb-") as tmp:
        frame = Path(tmp) / "frame.png"
        for seek in ("0.5", None):
            args = [settings.ffmpeg, "-y", "-v", "error"]
            if seek is not None:
                args += ["-ss", seek]
            args += ["-i", str(source), "-frames:v", "1", str(frame)]
            try:
                run_logged(args, check=True, capture_output=True, timeout=30, what="缩略图生成")
                with Image.open(frame) as image:
                    write_thumbnail(image, target)
            except Exception:
                continue
            if target.is_file() and target.stat().st_size > 0:
                return target
    return None


#: 换成 WebP 之前的缩略图文件名。只有迁移认识它。
_JPEG_THUMBNAIL_NAME = "thumbnail.jpg"


def migrate_jpeg_thumbnail(source: Path, kind: str, asset_directory: Path) -> None:
    """把旧的 JPEG 缩略图换成 WebP,然后删掉旧的。

    图片从原图重做 —— 旧 JPEG 里透明已经丢了,转格式救不回来;视频直接转那张 JPEG,
    省一次 ffmpeg 取帧。做不成也删旧的:缩略图接口取不到时会当场补一张。
    """
    old = asset_directory / _JPEG_THUMBNAIL_NAME
    if not old.is_file():
        return
    try:
        if kind == "image":
            generate_thumbnail(source, kind, asset_directory)
        else:
            with Image.open(old) as image:
                write_thumbnail(image, thumbnail_path(asset_directory))
    except Exception:
        pass
    old.unlink(missing_ok=True)
