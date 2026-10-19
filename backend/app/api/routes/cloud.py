"""「绑定 MosaelCloud」的本地入口。

云端凭据只走这里和本地库;渲染层拿不到 token。接口只做四件事:发起、完成、看状态、解绑。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.cloud import (
    CloudBindingCompleteIn,
    CloudBindingCompleteOut,
    CloudBindingOut,
    CloudBindingRemovedOut,
    CloudBindingStartIn,
    CloudBindingStartOut,
)
from app.domain import cloud_binding

router = APIRouter(tags=["cloud"])


def _fail(error: cloud_binding.CloudBindingError) -> None:
    raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message})


@router.post("/cloud/binding/start", response_model=CloudBindingStartOut)
def start_binding(body: CloudBindingStartIn, user: CurrentUser) -> dict:
    try:
        return cloud_binding.start(user, body.device_name)
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cloud_unreachable", "message": "Can't reach MosaelCloud. Check the network and try again."},
        ) from exc
    except cloud_binding.CloudBindingError as exc:
        _fail(exc)


@router.post("/cloud/binding/complete", response_model=CloudBindingCompleteOut)
def complete_binding(body: CloudBindingCompleteIn, user: CurrentUser, db: Tx) -> dict:
    try:
        return cloud_binding.complete(db, user, body.device_code)
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cloud_unreachable", "message": "Can't reach MosaelCloud. Check the network and try again."},
        ) from exc
    except cloud_binding.CloudBindingError as exc:
        _fail(exc)


@router.get("/cloud/binding", response_model=CloudBindingOut)
def get_binding(user: CurrentUser, db: DbSession) -> dict:
    return cloud_binding.status_of(db, user)


@router.delete("/cloud/binding", response_model=CloudBindingRemovedOut)
def remove_binding(user: CurrentUser, db: Tx) -> dict:
    return {"removed": cloud_binding.remove(db, user)}
