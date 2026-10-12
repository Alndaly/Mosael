"""从一份素材的像素算出一张蒙版,存成**新的**一份素材(ADR 0056 决定 6)。

**为什么这一步在后端。** 画笔那条路在浏览器里(见 components/generation/MaskEditor),而它读得到像素的
前提是图已经在这台机器上、并且这一屏正开着它。批量给一批图配同一块区域、智能体说「按亮度抠个蒙版」,
两件事都够不着那块画布 —— 所以后端要能自己从源图算一张出来。像素运算全在 `app/media/masks.py`,
这一层只管素材库的事:过闸、认得出这是不是一张图、登记出新的一份、记上出处。

**原素材一个字节都不动**,产出是另一份(和取帧、切宫格、转 GIF 同款)。产出**不打标签** —— 标签是
用户自己的词表(ADR 0056 决定 5 的修订),往里塞一个随语言变的词,中文用户和英文用户会得到两份
不一样的数据。名字带来源就够了。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import MASK, derived
from app.media.masks import LUMINANCE, MASK_FILENAME, MaskError, generate_mask
from app.media.paths import resolve_key

#: 素材名的长度上限(`db/model_slices/media.Asset.name` 是 String(240))。源图名字可以顶到 240,
#: 加上「蒙版 · 」这一截就会超 —— 截尾巴,前缀留着,一眼还是看得出它是哪一种产物。
MAX_NAME = 240


class MaskAssetError(LocalizedError, ValueError):
    """这份素材算不出蒙版。api 回 400。"""


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
    """按 `source` 阈值(`threshold` 0..1)从 `asset` 算一张蒙版,登记成新素材。

    形状四步的先后见 `media.masks.generate_mask`(阈值 → 反选 → 扩张/收缩 → 羽化)。`grow` 正数扩张、
    负数收缩,单位是像素;`project_id` 没给就放进原素材所在的项目。
    """
    if asset.kind != "image":
        raise MaskAssetError("maskErr_notImage", name=asset.name)
    origin = resolve_key(asset.file_key)
    if not origin.is_file():
        raise MaskAssetError("maskErr_fileMissing", name=asset.name)
    with tempfile.TemporaryDirectory(prefix="mosael-mask-") as folder:
        target = Path(folder) / MASK_FILENAME
        try:
            generate_mask(
                origin, target, source_kind=source, threshold=threshold, invert=invert, grow=grow, feather=feather,
            )
        except MaskError as exc:
            raise MaskAssetError.relay(exc) from exc
        except OSError as exc:
            #: 认不出的图片格式(PIL 打不开):说清楚是**这一份**读不了,不是"服务器错误"。
            raise MaskAssetError("maskErr_unreadable", name=asset.name) from exc
        return register_file_asset(
            db,
            workspace_id=asset.workspace_id,
            project_id=project_id or asset.project_id,
            source_path=target,
            #: 名字带来源(ADR 0056 决定 5):素材库里一行「蒙版 · xxx」就知道它是从哪张图来的。
            name=tr("maskAssetName", source=asset.name)[:MAX_NAME],
            source="generated",
            derived_from=derived(MASK, asset.id),
        )


__all__ = ["MAX_NAME", "MaskAssetError", "make_mask_asset"]
