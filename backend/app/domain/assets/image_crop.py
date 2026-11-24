"""从一张图里框一块留下来(ADR 0110)。

框是**四个比例**(左上角、宽、高,占摆正后原图宽 / 高的几分之几),不是像素:同一份设置换一张图照样说得通,
智能体说「留中间一半」也不用先查尺寸。这里先按 EXIF 摆正(和宫格切分同一条,否则框到的是侧着的那一边),再把比例
换成像素、夹进图里。原图不动;切出来的是一份新素材,记着从哪张图切出来(`derived_from`,见 assets/lineage)。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import CROP, derived
from app.media.paths import resolve_key

#: 切出来一边至少多少像素。再小就没法用了。
MIN_SIDE = 16


class ImageCropError(LocalizedError, ValueError):
    """切不了。带文案 key,可以直接给用户看。"""


@dataclass(frozen=True)
class CropBox:
    """框:左上角和宽高,都是占原图宽 / 高的比例(0–1)。"""

    x: float
    y: float
    width: float
    height: float

    @classmethod
    def whole(cls) -> CropBox:
        return cls(0.0, 0.0, 1.0, 1.0)

    def clamped(self) -> CropBox:
        """夹进图里:左上角在图内,宽高不超出右边、下边。"""
        x = min(max(self.x, 0.0), 1.0)
        y = min(max(self.y, 0.0), 1.0)
        return CropBox(x, y, min(max(self.width, 0.0), 1.0 - x), min(max(self.height, 0.0), 1.0 - y))

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """换成像素的 (左, 上, 右, 下),四舍五入。"""
        box = self.clamped()
        left, top = round(box.x * width), round(box.y * height)
        return left, top, min(width, left + round(box.width * width)), min(height, top + round(box.height * height))


def crop_image(db: Session, asset: Asset, box: CropBox) -> Asset:
    """按 `box` 切出一块,登记进素材库(同一个项目里),交回新素材。"""
    if asset.kind != "image":
        raise ImageCropError("cropErr_notImage", name=asset.name)
    source = resolve_key(asset.file_key)
    if not source.is_file():
        raise ImageCropError("cropErr_fileMissing", name=asset.name)
    jpeg = source.suffix.lower() in (".jpg", ".jpeg")
    with Image.open(source) as opened, tempfile.TemporaryDirectory(prefix="mosael-crop-") as folder:
        image = ImageOps.exif_transpose(opened)
        left, top, right, bottom = box.pixels(*image.size)
        if right - left < MIN_SIDE or bottom - top < MIN_SIDE:
            raise ImageCropError("cropErr_tooSmall", width=right - left, height=bottom - top, min=MIN_SIDE)
        piece = image.crop((left, top, right, bottom))
        target = Path(folder) / f"{Path(asset.name).stem or 'crop'}-crop.{'jpg' if jpeg else 'png'}"
        if jpeg:
            piece.convert("RGB").save(target, "JPEG", quality=95)
        else:
            piece.save(target, "PNG")
        return register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=asset.project_id,
            source_path=target,
            name=f"{asset.name} · crop",
            source="generated",
            derived_from=derived(CROP, asset.id),
            move=True,
        )


__all__ = ["CropBox", "ImageCropError", "MIN_SIDE", "crop_image"]
