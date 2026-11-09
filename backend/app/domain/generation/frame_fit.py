"""首帧、尾帧交给视频模型之前按视频的画幅摆正(ADR 0094)。

出图那一步交回的画幅和视频要的不一样时(方图当竖屏视频的首帧),模型各有各的处理 —— ComfyUI 的 H3 工作流
把图直接缩放到目标宽高,画面被压扁。漏斗在提交之前居中裁满,模型收到的就是目标画幅的那一张。

- 目标画幅从这次的参数里读,参数没说时按节点要的画幅(`target_aspect`);都没有就不动 —— 不猜;
- 只摆首帧、尾帧:参考图是「看着它画」,模型自己会构图;
- 差 `TOLERANCE` 以内不动(按 32 的倍数取整那点偏差);
- 裁好的一份登记成派生素材(来源链 `fit`、工序零件 `fitted_frame`),替换请求里原来那份;
  改了什么由调用方记进请求的 `fitted_frames`。
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.ai.providers.contracts.generation import FIRST_FRAME, LAST_FRAME
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.intermediates import FITTED_FRAME
from app.domain.assets.lineage import FIT, derived
from app.domain.generation.aspect import aspect_of_parameters, is_aspect_key, ratio_of
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

#: 要摆的角色。
FIT_ROLES = (FIRST_FRAME, LAST_FRAME)
#: 画幅差多少以内不动(相对差)。
TOLERANCE = 0.01


def target_aspect(parameters: Mapping[str, Any], wanted: str = "") -> tuple[float | None, str]:
    """这次视频要的画幅(宽 / 高)和写法:参数里说的优先(见 aspect.aspect_of_parameters,`adaptive` = 不摆);
    参数没说、节点说了要几比几(`wanted`)时按它。都没有返回 (None, "")。"""
    if any(is_aspect_key(key) for key, value in parameters.items() if value not in (None, "")) or parameters.get("size"):
        return aspect_of_parameters(parameters)
    ratio = ratio_of(wanted)
    return (ratio, wanted.strip()) if ratio is not None else (None, "")


@dataclass
class FittedFrames:
    """摆完之后的素材列表、改了哪几张(记进请求)、新登记的素材 id(这次生成被拒时删掉)。"""

    source_assets: list[dict[str, str]]
    receipt: list[dict[str, Any]] = field(default_factory=list)
    made_ids: list[str] = field(default_factory=list)


def fit_frames(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    source_assets: Sequence[dict[str, str]],
    parameters: Mapping[str, Any],
    wanted: str = "",
) -> FittedFrames:
    """把首帧、尾帧按这次的目标画幅(见 `target_aspect`)居中裁满。读不到画幅、画幅已经对、图读不了的,原样留着。"""
    sources = [dict(entry) for entry in source_assets]
    aspect, label = target_aspect(parameters, wanted)
    fitted = FittedFrames(source_assets=sources)
    if aspect is None:
        return fitted
    for entry in sources:
        if entry.get("role") not in FIT_ROLES:
            continue
        asset = db.get(Asset, str(entry.get("asset_id") or ""))
        if asset is None or asset.workspace_id != workspace_id or asset.kind != "image" or not asset.file_key:
            continue
        made = _crop(db, asset, aspect, label=label, project_id=project_id)
        if made is None:
            continue
        new_asset, before, after = made
        fitted.receipt.append({"role": entry["role"], "from": asset.id, "to": new_asset.id, "aspect": label,
                               "from_size": list(before), "to_size": list(after)})
        fitted.made_ids.append(new_asset.id)
        entry["asset_id"] = new_asset.id
    return fitted


def _crop(
    db: Session, asset: Asset, aspect: float, *, label: str, project_id: str | None,
) -> tuple[Asset, tuple[int, int], tuple[int, int]] | None:
    try:
        with Image.open(resolve_key(asset.file_key)) as image:
            image.load()
            width, height = image.size
            box = _centered_box(width, height, aspect)
            if box is None:
                return None
            cropped = image.crop(box)
    except (OSError, UnidentifiedImageError):
        #: 摆正是兜底,不是新的拒绝理由:读不了的图原样交出去。
        logger.info("首帧「%s」读不了,不按画幅摆", asset.name, exc_info=True)
        return None
    with tempfile.TemporaryDirectory(prefix="mosael-fit-") as tmp:
        target = Path(tmp) / "fitted.png"
        cropped.save(target)
        made = register_file_asset(
            db, workspace_id=asset.workspace_id, project_id=project_id or asset.project_id, source_path=target,
            name=f"{asset.name} · {label}", source="generated", derived_from=derived(FIT, asset.id),
            intermediate=FITTED_FRAME, move=True,
        )
    return made, (width, height), cropped.size


def _centered_box(width: int, height: int, aspect: float) -> tuple[int, int, int, int] | None:
    """居中裁满到 `aspect` 的那块(左、上、右、下);画幅差在 TOLERANCE 以内返回 None。"""
    if not width or not height or abs(width / height - aspect) / aspect <= TOLERANCE:
        return None
    if width / height > aspect:
        new_width = round(height * aspect)
        left = (width - new_width) // 2
        return left, 0, left + new_width, height
    new_height = round(width / aspect)
    top = (height - new_height) // 2
    return 0, top, width, top + new_height


__all__ = ["FIT_ROLES", "FittedFrames", "fit_frames", "target_aspect"]
