"""从参考库取一条进工作区的确认卡工具(use_reference,ADR 0091 §6)。

参考库的取用是「单条、由人发起」(ADR 0091 §3):智能体可以替人找(search_references 只读),但把哪一张取进来,
要人在卡上点头 —— 卡就是那一下「由人发起」。档位是 edit:取进来的是一份素材(和可选的一个姿势 / 服装资产),
删掉就回到原样;不花钱、不改应用之外的任何东西。

开卡时先问一次插件这一条是什么(名字、出处),卡上说清取的是哪一张、出自谁;批准时照常走 `reference_library.use`,
出处随素材写进 `external_source`。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment, get_current_locale
from app.db.models import User
from app.domain import reference_library
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.domain.plugins import instances as inst
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.runtime import PluginRuntimeError


def _instance(db: Session, payload: dict[str, Any], actor: str | None):
    """取用走的是**开卡这个人自己接的**那个参考库连接 —— 别人的连接、已经删掉的,一律不认。"""
    found = inst.owned(db, str(payload.get("connection_id") or ""), actor or "")
    if found is None:
        raise ConfirmationError("confirmErr_referenceConnectionGone")
    return found


def _validate_use_reference(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    instance = _instance(db, payload, actor)
    try:
        item = reference_library.item(
            db, instance, item_id=str(payload.get("item_id") or ""), collection=str(payload.get("collection") or ""),
        )
    except (reference_library.ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise ConfirmationError.relay(exc) from exc
    #: 卡上那句话要用的事实。下划线开头:参数表里不再列一遍(见前端 confirmationPayload)。
    names = item["name"]
    payload["_title"] = names.get("zh" if get_current_locale().startswith("zh") else "en") or names.get("en") or item["id"]
    payload["_library"] = instance.name
    payload["_author"] = item["provenance"].get("author", "")
    payload["_kind"] = item["kind"]


def _summarize_use_reference(db: Session, payload: dict[str, Any]) -> Summary:
    params = {
        "title": str(payload.get("_title") or payload.get("item_id") or ""),
        "library": str(payload.get("_library") or ""),
        "author": str(payload.get("_author") or "") or fragment("confirm_referenceAuthorUnknown"),
    }
    if payload.get("save_as_asset"):
        return "confirm_useReferenceAsAsset", {**params, "kind": fragment(f"entityKind_{payload.get('_kind') or 'pose'}")}
    return "confirm_useReference", params


def _execute_use_reference(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    instance = _instance(db, payload, actor)
    user = db.get(User, actor) if actor else None
    if user is None:
        raise ConfirmationError("confirmErr_referenceConnectionGone")
    try:
        used = reference_library.use(
            db, user, instance, workspace_id=confirmation.workspace_id,
            item_id=str(payload.get("item_id") or ""), collection=str(payload.get("collection") or ""),
            save_entity=bool(payload.get("save_as_asset")),
        )
    except (reference_library.ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise ConfirmationError.relay(exc) from exc
    return {"asset_id": used["asset_id"], "entity_id": used["entity_id"], "provenance": used["provenance"]}


confirmable_tool(ConfirmableTool(
    name="use_reference",
    permission="edit",
    cost="none",
    writes=("assets", "entities"),
    summarize=_summarize_use_reference,
    execute=_execute_use_reference,
    validate=_validate_use_reference,
))
