"""照着一张(几张)参考图画的那几种节点用哪个图片模型:资产格的「补全多角度」「生成表情」、给一张图重新打光(ADR 0108)。

只看得到文字的模型画不出「同一个」、也改不了「这一张」,所以只认**收参考图**的图片模型。模型下拉(选项来源
`reference_image_models`,见 field_options)、运行前的检查、节点跑的时候挑哪一个,问的都是这里。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.entities.mentions import REFERENCE_ROLE
from app.domain.generation import resolution as generation_resolution
from app.domain.workflows.errors import WorkflowDomainError


def works_from_reference_images(option: dict[str, Any]) -> bool:
    """这个生成选项**只给参考图就能跑**:收参考图,而且没有别的必填素材(`requires_source` 的每一条都认参考图)。

    后一半挡的是局部重绘那种图:它也收参考图,却必须再给一份蒙版 —— 挑它来补角度、来打光,一跑就是「必须给一份蒙版」。
    """

    capabilities = option.get("capabilities") or {}
    takes = REFERENCE_ROLE in (capabilities.get("parameter_keys") or ()) \
        and bool((capabilities.get("source_limits") or {}).get(REFERENCE_ROLE))
    needs_more = any(REFERENCE_ROLE not in options for options in capabilities.get("requires_source") or [])
    return bool(option.get("adapter_available")) and takes and not needs_more


def automatic_reference_model(options: list[dict[str, Any]]) -> dict[str, Any] | None:
    """没点名时用哪个图片模型:他设的默认图片模型正好收参考图就用它,否则用第一个收参考图的。

    和说话照片 / 改口型挑模型同一个先后(talking._pick_model)。此前只认默认:默认的图片模型只会文生图时,
    下拉里明明列着能用的,留空却报「不收参考图」。模型下拉标「默认」的也是这一个(field_options)。
    """
    usable = [one for one in options if works_from_reference_images(one)]
    return next((one for one in usable if one.get("is_default")), None) or (usable[0] if usable else None)


def reference_model(db: Session, choice: str, actor_id: str | None) -> dict[str, Any]:
    """用哪个图片模型:点名的那一个(`reference_image_models` 的选项 id),没点名见 automatic_reference_model。"""

    options = generation_resolution.generation_options(db, "image", user_id=actor_id)
    if not choice:
        picked = automatic_reference_model(options)
        if picked is None:
            raise WorkflowDomainError("wfErr_referenceModelNone")
        return picked
    picked = next((one for one in options if one["id"] == choice), None)
    if picked is None:
        raise WorkflowDomainError("wfErr_referenceModelMissing")
    if not works_from_reference_images(picked):
        raise WorkflowDomainError("wfErr_referenceModelNoReferences", params={"model": picked["model_label"]})
    return picked
