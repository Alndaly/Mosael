"""蒙版素材:**唯一的写出口**,和喂给它的两种生产者(ADR 0057 决定 2)。

**一种形状。** 蒙版素材一律是 `L` 模式(单通道、没有 alpha)的 PNG,白 = 要改的地方;有源图时像素尺寸和
**摆正后的**源图一模一样、出处记 `op = "mask"`、名字「蒙版 · <源图名>」。没有源图(新建的空白蒙版)就是它自己的
尺寸、不带出处、名字「蒙版 · 空白」。

**一个出口。** `write_mask_asset` 是登记蒙版素材的唯一地方 —— 落盘、起名、记出处都在这里。别处要产蒙版,把
单通道字节交过来,不要另起一条 `register_file_asset(..., derived_from=derived(MASK, …))`:那样就又多了一种形状。

**两种生产者:**

- `make_mask_asset` —— **按配方算**:源图 + 阈值 / 反选 / 扩张 / 羽化(素材库「生成蒙版」、智能体 `create_mask`);
- `save_painted_mask` —— **画出来的**:编辑器上传的那张图,按契约归一(红通道、透明当黑、缩放到源图尺寸)。

**原素材一个字节都不动**,产出是另一份(和取帧、切宫格、转 GIF 同款)。产出**不打标签** —— 标签是用户自己的
词表(ADR 0056 决定 5),往里塞一个随语言变的词,中文用户和英文用户会得到两份不一样的数据。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import BinaryIO

from PIL import UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import MASK, derived
from app.media.masks import (
    LUMINANCE,
    MASK_FILENAME,
    MaskError,
    oriented_size,
    painted_mask,
    recipe_mask,
    write_mask_png,
)
from app.media.paths import resolve_key

#: 素材名的长度上限(`db/model_slices/media.Asset.name` 是 String(240))。源图名字可以顶到 240,
#: 加上「蒙版 · 」这一截就会超 —— 截尾巴,前缀留着,一眼还是看得出它是哪一种产物。
MAX_NAME = 240


class MaskAssetError(LocalizedError, ValueError):
    """这份素材当不了蒙版的源图,或者交上来的东西不是一张图。api 回 400。"""


def mask_source_file(asset: Asset) -> Path:
    """蒙版的源图在盘上的那个文件。源图只能是**图片**(ADR 0057 决定 1:编辑器只画得出图片底图)。"""
    if asset.kind != "image":
        raise MaskAssetError("maskErr_notImage", name=asset.name)
    origin = resolve_key(asset.file_key)
    if not origin.is_file():
        raise MaskAssetError("maskErr_fileMissing", name=asset.name)
    return origin


def write_mask_asset(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    source: Asset | None,
    mask: bytes,
    size: tuple[int, int],
) -> Asset:
    """**唯一的写出口**:一份单通道蒙版(`mask`,长度 = 宽 × 高)登记成一份蒙版素材。

    调用方负责把像素交成契约那个形状(两种生产者各自归一,见模块头);这里只做三件事 —— 落 `L` 模式 PNG
    (没有 alpha 通道可以出错)、起名、记出处。`project_id` 没给就跟着源图走。
    """
    with tempfile.TemporaryDirectory(prefix="mosael-mask-") as folder:
        target = write_mask_png(Path(folder) / MASK_FILENAME, mask, size)
        return register_file_asset(
            db,
            workspace_id=workspace_id,
            project_id=project_id or (source.project_id if source is not None else None),
            source_path=target,
            #: 名字带来源(ADR 0056 决定 5):素材库里一行「蒙版 · xxx」就知道它是从哪张图来的。
            name=tr("maskAssetName", source=source.name if source is not None else tr("maskAssetNoSource"))[:MAX_NAME],
            source="generated",
            derived_from=derived(MASK, source.id) if source is not None else (),
        )


def make_mask_asset(
    db: Session,
    asset: Asset,
    *,
    source: str = LUMINANCE,
    threshold: float = 0.5,
    invert: bool = False,
    grow: int = 0,
    feather: float = 0,
    project_id: str | None = None,
) -> Asset:
    """**按配方算**:按 `source` 阈值(`threshold` 0..1)从 `asset` 算一张蒙版,交给写出口。

    形状四步的先后见 `media.masks.recipe_mask`(阈值 → 反选 → 扩张/收缩 → 羽化)。`grow` 正数扩张、
    负数收缩,单位是像素。
    """
    origin = mask_source_file(asset)
    try:
        mask, size = recipe_mask(
            origin, source_kind=source, threshold=threshold, invert=invert, grow=grow, feather=feather,
        )
    except MaskError as exc:
        raise MaskAssetError.relay(exc) from exc
    except OSError as exc:
        #: 认不出的图片格式(PIL 打不开):说清楚是**这一份**读不了,不是"服务器错误"。
        raise MaskAssetError("maskErr_unreadable", name=asset.name) from exc
    return write_mask_asset(
        db, workspace_id=asset.workspace_id, project_id=project_id, source=asset, mask=mask, size=size,
    )


def save_painted_mask(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    source: Asset | None,
    painted: BinaryIO,
    filename: str = "",
) -> Asset:
    """**画出来的**:编辑器交上来的那张图归一成契约那个形状(红通道、透明当黑、缩放到源图尺寸),交给写出口。

    编辑器的文档长边封顶 4096(浏览器的画布内存),源图更大时画出来的那张比源图小 —— 出口按源图尺寸缩回去,
    于是"蒙版和源图一样大"这条不靠编辑器记得。`source` 由调用方过完闸再交进来(同一个工作区、看得见)。
    """
    size = None
    if source is not None:
        origin = mask_source_file(source)
        try:
            size = oriented_size(origin)
        except OSError as exc:
            raise MaskAssetError("maskErr_unreadable", name=source.name) from exc
    try:
        mask, actual = painted_mask(painted, size)
    except (UnidentifiedImageError, OSError) as exc:
        raise MaskAssetError("maskErr_unreadable", name=filename or MASK_FILENAME) from exc
    return write_mask_asset(
        db, workspace_id=workspace_id, project_id=project_id, source=source, mask=mask, size=actual,
    )


__all__ = [
    "MAX_NAME",
    "MaskAssetError",
    "make_mask_asset",
    "mask_source_file",
    "save_painted_mask",
    "write_mask_asset",
]
