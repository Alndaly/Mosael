"""图片格上的两件「改这一张」(ADR 0110):框一块留下来(裁切)、涂一块让模型改(局部重绘)。

- 裁切本机做(`assets/image_crop`),框是四个比例;
- 重绘交给一个能改图的模型(`reference_models.inpaint_model`,收蒙版的排前面),结果由 `assets/inpaint_composite`
  按蒙版贴回原图 —— 「只改这一块」由合成保证，不靠模型自觉。模型交回的整张记成中间产物(`inpaint_draft`),
  素材库默认不列；贴好的那张是产出。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers.contracts.generation import MASK
from app.core.i18n import get_current_locale, t
from app.db.models import Asset
from app.domain.assets.image_crop import CropBox, ImageCropError, crop_image
from app.domain.assets.inpaint_composite import InpaintCompositeError, composite_inpaint
from app.domain.assets.intermediates import INPAINT_DRAFT
from app.domain.entities.mentions import REFERENCE_ROLE
from app.domain.jobs import current_actor
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors.inputs import _asset_in
from app.domain.workflows.executors.reference_models import inpaint_model, reference_limit, takes_mask
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.subjobs import generate_one


def _fraction(config: dict[str, Any], key: str, fallback: float) -> float:
    value = config.get(key)
    try:
        return float(value) if value not in (None, "") else fallback
    except (TypeError, ValueError):
        return fallback


def crop_box(config: dict[str, Any]) -> CropBox:
    """节点上那四格 → 框:没写、写错的按整张图。"""
    whole = CropBox.whole()
    return CropBox(
        _fraction(config, "crop_x", whole.x),
        _fraction(config, "crop_y", whole.y),
        _fraction(config, "crop_width", whole.width),
        _fraction(config, "crop_height", whole.height),
    )


@register("image_crop")
def image_crop(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """框一块留下来,交回切出来的那张。"""

    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    try:
        piece = crop_image(db, asset, crop_box(config))
    except ImageCropError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    return {"asset_id": piece.id, "source_asset_id": asset.id}


def _frame_of(asset: Asset) -> str:
    """原图的宽 × 高(「1280x720」),读不出来是空串 —— 那就照模型的默认出(贴回时照样缩放到原图)。"""
    info = asset.media_info if isinstance(asset.media_info, dict) else {}
    width, height = info.get("width"), info.get("height")
    return f"{int(width)}x{int(height)}" if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width and height else ""


def _inpaint_order(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """这一单交什么。模型收蒙版:原图当参考、蒙版当蒙版，提示词就是那一句；不收蒙版的：收得下两张参考图就把蒙版当
    第二张、提示词前面说清楚第二张是什么；只收一张的只给原图(改哪儿由贴回时的蒙版管)。"""
    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    mask = _asset_in(db, scope, str(config.get("mask_asset_id") or "").strip())
    text = str(config.get("prompt") or "").strip()
    model = inpaint_model(db, str(config.get("model") or "").strip(), current_actor(db))
    sources = [{"asset_id": asset.id, "role": REFERENCE_ROLE}]
    prompt = text
    if takes_mask(model):
        sources.append({"asset_id": mask.id, "role": MASK})
    elif reference_limit(model) >= 2:
        sources.append({"asset_id": mask.id, "role": REFERENCE_ROLE})
        prompt = t("inpaint_instruction", get_current_locale(), text=text)
    return {
        "provider": model["provider"],
        "provider_profile_id": model["provider_profile_id"],
        "model": model["model"],
        "kind": "image",
        "prompt": prompt,
        "negative_prompt": "",
        "parameters": {},
        "source_assets": sources,
        "frame_aspect": _frame_of(asset),
    }


def _inpaint_inputs(db: Session, scope: RunScope, config: dict[str, Any]) -> tuple[Asset, Asset]:
    """跑之前先查齐：原图、蒙版、那一句 —— 缺了在下单之前就说，不白花一次生成。"""
    if not str(config.get("mask_asset_id") or "").strip():
        raise WorkflowDomainError("wfErr_inpaintNoMask")
    if not str(config.get("prompt") or "").strip():
        raise WorkflowDomainError("wfErr_inpaintNoPrompt")
    return (_asset_in(db, scope, str(config.get("asset_id") or "").strip()),
            _asset_in(db, scope, str(config.get("mask_asset_id") or "").strip()))


@register("image_inpaint")
def image_inpaint(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """局部重绘：一次生成，结果按蒙版贴回原图，交回贴好的那张。"""

    original_id, mask_id = (one.id for one in _inpaint_inputs(db, scope, config))
    made = generate_one(db, scope, config, lambda: _inpaint_order(db, scope, config))
    #: 等生成时会话交还过一次(subjobs.generate_one),先前取的对象都脱管了 —— 按 id 重新取。
    painted = db.get(Asset, made["asset_id"] or (made["asset_ids"][0] if made["asset_ids"] else ""))
    if painted is None:
        raise WorkflowDomainError("wfErr_inpaintNoResult")
    painted.intermediate = INPAINT_DRAFT
    original, mask = db.get(Asset, original_id), db.get(Asset, mask_id)
    try:
        merged = composite_inpaint(db, original=original, painted=painted, mask=mask)
    except InpaintCompositeError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    return {"asset_id": merged.id, "asset_ids": [merged.id]}
