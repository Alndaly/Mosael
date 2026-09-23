from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from app.core.child_process import run_logged
from app.media.image_preview import browser_compatible_image

#: WebP 而不是 JPEG:**JPEG 没有透明通道**。带透明的 PNG(图标、抠图)转成 JPEG 时透明像素
#: 里残留的颜色全露出来 —— 四角一块黑、边缘一圈白色毛刺,而原图明明是透明的。
THUMBNAIL_NAME = "thumbnail.webp"
THUMBNAIL_MEDIA_TYPE = "image/webp"
THUMBNAIL_WIDTH = 320


def thumbnail_path(asset_directory: Path) -> Path:
    return asset_directory / THUMBNAIL_NAME


def write_thumbnail(image: Image.Image, target: Path) -> None:
    """按宽 320 等比缩小(不放大)写成 WebP;有透明就留着透明。"""
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in {"RGBA", "LA", "PA"} or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    if image.width > THUMBNAIL_WIDTH:
        height = max(1, round(image.height * THUMBNAIL_WIDTH / image.width))
        image = image.resize((THUMBNAIL_WIDTH, height), Image.Resampling.LANCZOS)
    image.save(target, "WEBP", quality=82, method=4)


def generate_thumbnail(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """Best-effort thumbnail extraction; import must never fail because of it."""
    if kind == "audio":
        return None
    target = thumbnail_path(asset_directory)
    if kind == "image":
        compatible = browser_compatible_image(source, asset_directory)
        if compatible is None:
            return None
        try:
            with Image.open(compatible[0]) as image:
                write_thumbnail(image, target)
        except Exception:
            return None
        return target if target.is_file() and target.stat().st_size > 0 else None
    # 视频:ffmpeg 取一帧成 PNG,再走同一个写法。0.5s 跳过片头黑场;超短片段 seek 会落在
    # 片尾之后取不到帧,退回首帧再试。
    with tempfile.TemporaryDirectory(prefix="mosael-thumb-") as tmp:
        frame = Path(tmp) / "frame.png"
        for seek in ("0.5", None):
            args = ["ffmpeg", "-y", "-v", "error"]
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
