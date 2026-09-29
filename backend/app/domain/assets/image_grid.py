"""把一张拼图(九宫格、四宫格、分镜条……)按行列等分切成几张单图,各自进素材库。

AI 出图常常一次交回一张拼好的宫格(九宫格表情包、四格分镜、多角度设定图);要单独拿去用,得一张张切出来。
这里**只做等分**:宫格图本来就是等分排的,不猜内容边界 —— 猜错了切出来的是半张脸。

宫格之间常有一道白边或黑边(出图模型画的分隔线)。`trim_gutter` 打开时,每一张再把四周和角上颜色相同的
那一圈去掉,**每边最多去掉 6%**:分隔线只是一道细线,去得再多就是在啃画面了(白底的商品图四周本来就是白的)。
原图不动;切出来的每一张记着它从哪张图、第几行第几列切出来(`media_info`)。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageOps
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.media.paths import resolve_key

#: 预设的切法:`行x列`。上限 12 张 —— 画板一轮最多落 12 格(boards.canvas.MAX_DERIVED_ITEMS)。
GRIDS: dict[str, tuple[int, int]] = {
    "2x2": (2, 2),
    "3x3": (3, 3),
    "1x2": (1, 2),
    "2x1": (2, 1),
    "1x3": (1, 3),
    "3x1": (3, 1),
    "2x3": (2, 3),
    "3x2": (3, 2),
    "3x4": (3, 4),
    "4x3": (4, 3),
}
DEFAULT_GRID = "3x3"
#: 每一张至少多大(像素)。再小切出来就没法用了。
MIN_TILE = 32
#: 去分隔线时每边最多去掉多少(占这一张的比例)。
MAX_GUTTER = 0.06
#: 和角上那个颜色差多少以内算「同一种颜色」(0–255)。JPEG 的压缩噪声在十几以内。
GUTTER_TOLERANCE = 24


class ImageGridError(LocalizedError, ValueError):
    """切不了。带文案 key,可以直接给用户看。"""


def parse_grid(value: str) -> tuple[int, int]:
    grid = GRIDS.get(str(value or DEFAULT_GRID).strip().lower())
    if grid is None:
        raise ImageGridError("gridErr_unknownGrid", grid=str(value))
    return grid


def tile_boxes(width: int, height: int, rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    """按行从左到右、从上到下,每一张的范围。除不尽的像素按四舍五入分给相邻两张,不丢不重。"""
    return [
        (round(col * width / cols), round(row * height / rows), round((col + 1) * width / cols), round((row + 1) * height / rows))
        for row in range(rows)
        for col in range(cols)
    ]


def trim_gutter(tile: Image.Image) -> Image.Image:
    """去掉这一张四周和左上角同色的那一圈,每边最多 MAX_GUTTER。四周没有同色的一圈就原样返回。"""
    rgb = tile.convert("RGB")
    width, height = rgb.size
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    mask = ImageChops.difference(rgb, background).convert("L").point(lambda value: 255 if value > GUTTER_TOLERANCE else 0)
    box = mask.getbbox()
    if box is None:
        return tile
    limit_x, limit_y = int(width * MAX_GUTTER), int(height * MAX_GUTTER)
    left, top = min(box[0], limit_x), min(box[1], limit_y)
    right, bottom = max(box[2], width - limit_x), max(box[3], height - limit_y)
    if (left, top, right, bottom) == (0, 0, width, height):
        return tile
    return tile.crop((left, top, right, bottom))


def split_image_grid(db: Session, asset: Asset, *, grid: str = DEFAULT_GRID, gutter: bool = False) -> list[Asset]:
    """切成 行×列 张,按阅读顺序登记进素材库,交回新素材(同一个项目里)。"""
    if asset.kind != "image":
        raise ImageGridError("gridErr_notImage", name=asset.name)
    rows, cols = parse_grid(grid)
    source = resolve_key(asset.file_key)
    if not source.is_file():
        raise ImageGridError("gridErr_fileMissing", name=asset.name)
    jpeg = source.suffix.lower() in (".jpg", ".jpeg")
    made: list[Asset] = []
    with Image.open(source) as opened, tempfile.TemporaryDirectory(prefix="mosael-grid-") as folder:
        #: 手机拍的图靠 EXIF 标方向;不先摆正的话,切出来的「第一行」是侧着的那一边。
        image = ImageOps.exif_transpose(opened)
        width, height = image.size
        if width // cols < MIN_TILE or height // rows < MIN_TILE:
            raise ImageGridError("gridErr_tooSmall", width=width, height=height, grid=f"{rows}×{cols}")
        for index, box in enumerate(tile_boxes(width, height, rows, cols)):
            tile = image.crop(box)
            if gutter:
                tile = trim_gutter(tile)
            target = Path(folder) / f"{Path(asset.name).stem or 'tile'}-{index + 1}.{'jpg' if jpeg else 'png'}"
            if jpeg:
                tile.convert("RGB").save(target, "JPEG", quality=95)
            else:
                tile.save(target, "PNG")
            piece = register_file_asset(
                db,
                workspace_id=asset.workspace_id,
                project_id=asset.project_id,
                source_path=target,
                name=f"{asset.name} · {index + 1}",
                source="generated",
            )
            piece.media_info = {
                **(piece.media_info or {}),
                "derived_from_asset_id": asset.id,
                "derivation": "image_grid_split",
                "grid": f"{rows}x{cols}",
                "grid_cell": [index // cols + 1, index % cols + 1],
            }
            made.append(piece)
    return made


__all__ = ["DEFAULT_GRID", "GRIDS", "ImageGridError", "parse_grid", "split_image_grid", "tile_boxes", "trim_gutter"]
