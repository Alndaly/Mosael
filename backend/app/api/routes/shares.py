from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.core.permissions import ensure_workspace_access
from app.domain import sharing

router = APIRouter(tags=["shares"])

"""把「我的东西」放进一个工作区,或者收回来。

共享是**主人的授权动作**:别人替他做出来的授权不叫授权。所以这两条路由只认主人 —— 工作区的
admin 也不行,他管的是工作区里的内容,不是别人的登录态。
"""


class ShareRequest(BaseModel):
    workspace_id: str


def _owned(db: DbSession, user: CurrentUser, kind: str, resource_id: str, workspace_id: str):
    try:
        model = sharing.model_for(kind)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # 先确认他在目标工作区里 —— 不然共享就成了往别人的工作区里塞东西。
    ensure_workspace_access(db, user, workspace_id)
    resource = db.get(model, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Not found")
    if resource.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="只有它的主人可以共享或收回")
    return resource


@router.post("/shares/{kind}/{resource_id}")
def share_resource(
    kind: str, resource_id: str, body: ShareRequest, db: DbSession, user: CurrentUser
) -> dict:
    _owned(db, user, kind, resource_id, body.workspace_id)
    sharing.share(db, kind, resource_id, body.workspace_id, user.id)
    db.commit()
    return {"kind": kind, "resource_id": resource_id, "workspaces": sharing.shared_workspaces(db, kind, resource_id)}


@router.delete("/shares/{kind}/{resource_id}")
def unshare_resource(
    kind: str, resource_id: str, body: ShareRequest, db: DbSession, user: CurrentUser
) -> dict:
    _owned(db, user, kind, resource_id, body.workspace_id)
    sharing.unshare(db, kind, resource_id, body.workspace_id)
    db.commit()
    return {"kind": kind, "resource_id": resource_id, "workspaces": sharing.shared_workspaces(db, kind, resource_id)}


@router.get("/shares/{kind}/{resource_id}")
def list_shares(kind: str, resource_id: str, db: DbSession, user: CurrentUser) -> dict:
    try:
        model = sharing.model_for(kind)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    resource = db.get(model, resource_id)
    if resource is None or not sharing.may_use(db, kind, resource, user):
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "kind": kind,
        "resource_id": resource_id,
        "owner_user_id": resource.owner_user_id,
        "is_mine": resource.owner_user_id == user.id,
        "workspaces": sharing.shared_workspaces(db, kind, resource_id),
    }
