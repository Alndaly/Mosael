"""局部重绘的最后一步:把模型画出来的那张按蒙版贴回原图(ADR 0110)。

「只改这一块」由这里保证，不靠模型自觉：通用改图模型会顺手改别处(肤色、背景、构图微移),收蒙版的模型也常把整张
重新编码一遍。生成图缩放到原图(摆正后)的尺寸，蒙版边缘羽化，蒙版外逐像素是原图。

产出是一份新素材，出处是原图、生成的那张和蒙版(`inpaint`,见 assets/lineage)—— 含 AI 由生成的那张继承。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import INPAINT, derived
from app.media.paths import resolve_key

#: 羽化半径占原图短边的比例，至少 MIN_FEATHER 像素：硬边贴回去，接缝一眼就看得出来。
FEATHER_RATIO = 0.01
MIN_FEATHER = 2


class InpaintCompositeError(LocalizedError, ValueError):
    """贴不回去。带文案 key,可以直接给用户看。"""


def _upright(asset: Asset) -> Image.Image:
    path = resolve_key(asset.file_key)
    if asset.kind != "image" or not path.is_file():
        raise InpaintCompositeError("inpaintErr_fileMissing", name=asset.name)
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).copy()


def feather_radius(size: tuple[int, int]) -> float:
    return max(MIN_FEATHER, min(size) * FEATHER_RATIO)


def composite(original: Image.Image, painted: Image.Image, mask: Image.Image) -> Image.Image:
    """按蒙版(白 = 换成 `painted`)把两张合成一张，尺寸是 `original` 的。"""
    size = original.size
    soft = mask.convert("L").resize(size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(feather_radius(size)))
    mode = "RGBA" if "A" in original.getbands() else "RGB"
    base = original.convert(mode)
    return Image.composite(painted.convert(mode).resize(size, Image.Resampling.LANCZOS), base, soft)


def composite_inpaint(db: Session, *, original: Asset, painted: Asset, mask: Asset) -> Asset:
    """把 `painted` 按 `mask` 贴回 `original`,登记成一份新素材(和原图同一个项目)。"""
    merged = composite(_upright(original), _upright(painted), _upright(mask))
    jpeg = Path(original.file_key or "").suffix.lower() in (".jpg", ".jpeg") and merged.mode == "RGB"
    with tempfile.TemporaryDirectory(prefix="mosael-inpaint-") as folder:
        target = Path(folder) / f"{Path(original.name).stem or 'inpaint'}-inpaint.{'jpg' if jpeg else 'png'}"
        if jpeg:
            merged.save(target, "JPEG", quality=95)
        else:
            merged.save(target, "PNG")
        return register_file_asset(
            db,
            workspace_id=original.workspace_id,
            project_id=original.project_id,
            source_path=target,
            name=f"{original.name} · inpaint",
            source="generated",
            derived_from=derived(INPAINT, original.id, painted.id, mask.id),
            move=True,
        )


__all__ = ["InpaintCompositeError", "composite", "composite_inpaint", "feather_radius"]
