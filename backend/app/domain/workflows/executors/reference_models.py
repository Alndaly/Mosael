"""照着一张(几张)参考图画的那几种节点用哪个图片模型:资产格的「补全多角度」「生成表情」、给一张图重新打光(ADR 0108)、
局部重绘(ADR 0110)。

只看得到文字的模型画不出「同一个」、也改不了「这一张」,所以只认**收参考图**的图片模型。模型下拉(选项来源
`reference_image_models`,见 field_options)、运行前的检查、节点跑的时候挑哪一个,问的都是这里。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers.contracts.generation import MASK
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


def takes_mask(option: dict[str, Any]) -> bool:
    """这个生成选项收蒙版(局部重绘那种):蒙版能和参考图一起交出去。"""

    capabilities = option.get("capabilities") or {}
    return MASK in (capabilities.get("parameter_keys") or ()) and bool((capabilities.get("source_limits") or {}).get(MASK))


def reference_limit(option: dict[str, Any]) -> int:
    """这个生成选项最多收几张参考图。"""

    return int(((option.get("capabilities") or {}).get("source_limits") or {}).get(REFERENCE_ROLE) or 0)


def works_for_inpaint(option: dict[str, Any]) -> bool:
    """局部重绘(ADR 0110)能用它:收参考图、能跑起来,而且 `requires_source` 的每一条都由参考图或蒙版满足。

    比 works_from_reference_images 宽一格:收蒙版的那种(必须再给一份蒙版)在这里正合适 —— 重绘本来就带着蒙版。
    """

    capabilities = option.get("capabilities") or {}
    satisfiable = all(REFERENCE_ROLE in options or MASK in options for options in capabilities.get("requires_source") or [])
    return bool(option.get("adapter_available")) and reference_limit(option) > 0 and satisfiable


def inpaint_candidates(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """重绘能用的图片模型,**收蒙版的排前面**(同一组里保持生成目录的先后)。"""

    usable = [one for one in options if works_for_inpaint(one)]
    return [one for one in usable if takes_mask(one)] + [one for one in usable if not takes_mask(one)]


def automatic_inpaint_model(options: list[dict[str, Any]]) -> dict[str, Any] | None:
    """重绘没点名时用哪个:他设的默认图片模型够格就用它,否则第一个收蒙版的,再否则第一个收参考图的。"""

    usable = inpaint_candidates(options)
    return next((one for one in usable if one.get("is_default")), None) or (usable[0] if usable else None)


def inpaint_model(db: Session, choice: str, actor_id: str | None) -> dict[str, Any]:
    """重绘用哪个图片模型:点名的那一个(`inpaint_models` 的选项 id),没点名见 automatic_inpaint_model。"""

    options = generation_resolution.generation_options(db, "image", user_id=actor_id)
    if not choice:
        picked = automatic_inpaint_model(options)
        if picked is None:
            raise WorkflowDomainError("wfErr_referenceModelNone")
        return picked
    picked = next((one for one in options if one["id"] == choice), None)
    if picked is None:
        raise WorkflowDomainError("wfErr_referenceModelMissing")
    if not works_for_inpaint(picked):
        raise WorkflowDomainError("wfErr_referenceModelNoReferences", params={"model": picked["model_label"]})
    return picked


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
