"""参考库(ADR 0091 §3):只读的外部参考图集,按连接浏览、搜索、取用。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.base import ApiModel
from app.core.i18n import tr
from app.domain import reference_library
from app.domain.plugins import instances as inst
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.runtime import PluginRuntimeError

router = APIRouter(tags=["reference-library"])


class ReferenceUseIn(ApiModel):
    workspace_id: str
    item_id: str
    collection: str = ""
    #: 「用作素材」取哪个视角(`views[].role`);空 = 第一张。「存为资产」每个视角各取一张,不看它。
    role: str = ""
    save_entity: bool = False


def _instance(db, user, instance_id: str):
    found = inst.owned(db, instance_id, user.id)
    if found is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_pluginConnectionNotFound"))
    return found


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@router.get("/reference-library/connections")
def list_reference_libraries(db: DbSession, user: CurrentUser) -> list[dict[str, str]]:
    return reference_library.connections(db, user.id)


@router.get("/reference-library/{instance_id}/collections")
def list_reference_collections(instance_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    try:
        return reference_library.collections(db, _instance(db, user, instance_id))
    except (reference_library.ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise _fail(exc) from exc


@router.get("/reference-library/{instance_id}/search")
def search_reference_items(
    instance_id: str,
    db: DbSession,
    user: CurrentUser,
    collection: str = "",
    q: str = "",
    cursor: str = "",
    limit: int = Query(40, ge=1, le=200),
    filters: str = "",
) -> dict:
    try:
        parsed = json.loads(filters) if filters.strip() else {}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=tr("referenceLibErr_badFilters")) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail=tr("referenceLibErr_badFilters"))
    try:
        return reference_library.search(
            db, _instance(db, user, instance_id), collection=collection, q=q,
            filters={str(k): str(v) for k, v in parsed.items() if v not in (None, "")},
            cursor=cursor, limit=limit,
        )
    except (reference_library.ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise _fail(exc) from exc


@router.get("/reference-library/{instance_id}/item")
def get_reference_item(
    instance_id: str, db: DbSession, user: CurrentUser, item_id: str, collection: str = ""
) -> dict:
    try:
        return reference_library.item(
            db, _instance(db, user, instance_id), item_id=item_id, collection=collection,
        )
    except (reference_library.ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise _fail(exc) from exc


@router.post("/reference-library/{instance_id}/use")
def use_reference_item(instance_id: str, body: ReferenceUseIn, db: Tx, user: CurrentUser) -> dict:
    try:
        return reference_library.use(
            db, user, _instance(db, user, instance_id),
            workspace_id=body.workspace_id, item_id=body.item_id,
            collection=body.collection, role=body.role, save_entity=body.save_entity,
        )
    except (reference_library.ReferenceLibraryError, PluginDomainError, PluginRuntimeError) as exc:
        raise _fail(exc) from exc
