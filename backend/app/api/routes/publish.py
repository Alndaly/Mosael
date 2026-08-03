from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.domain import sharing
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    PublishAccountCreate,
    PublishAccountOut,
    PublishAccountUpdate,
    PublishCopyRequest,
    PublishCopyResponse,
    PublishCreate,
    PublishPlatformOut,
    PublishTaskOut,
)
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Asset, PublishAccount, PublishTask
from app.domain.publish import (
    PUBLISH_PLATFORMS,
    PublishDomainError,
    create_account,
    list_tasks,
    start_publish,
    task_with_status,
)

router = APIRouter(tags=["publish"])


@router.get("/publish/platforms", response_model=list[PublishPlatformOut])
def platforms() -> list[dict]:
    return [
        {
            "platform": key,
            "label": meta["label"],
            "description": meta["description"],
            "config": meta["config"],
            "title_max": meta.get("title_max", 300),
            "short_title": meta.get("short_title", False),
        }
        for key, meta in PUBLISH_PLATFORMS.items()
    ]


@router.get("/publish/accounts", response_model=list[PublishAccountOut])
def list_accounts(workspace_id: str, db: DbSession, user: CurrentUser) -> list[PublishAccount]:
    ensure_workspace_access(db, user, workspace_id)
    return list(
        db.scalars(
            select(PublishAccount)
            .where(PublishAccount.workspace_id == workspace_id, sharing.visible_filter('publish_account', user, workspace_id))
            .order_by(PublishAccount.created_at)
        )
    )


@router.post("/publish/accounts", response_model=PublishAccountOut)
def create_account_route(body: PublishAccountCreate, db: DbSession, user: CurrentUser) -> PublishAccount:
    ensure_workspace_perm(db, user, body.workspace_id, "publish")
    try:
        return create_account(
            db,
            workspace_id=body.workspace_id,
            platform=body.platform,
            name=body.name,
            config=body.config,
            owner=user,
            proxy=body.proxy,
        )
    except PublishDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/publish/accounts/{account_id}", response_model=PublishAccountOut)
def update_account(account_id: str, body: PublishAccountUpdate, db: DbSession, user: CurrentUser) -> PublishAccount:
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("name"):
        account.name = changes["name"]
    if changes.get("config") is not None:
        account.config = changes["config"]
    if changes.get("enabled") is not None:
        account.enabled = changes["enabled"]
    if "proxy" in changes:
        # 空串 → 清成 None(直连);否则存去空白后的值。
        account.proxy = (changes["proxy"] or "").strip() or None
    db.commit()
    db.refresh(account)
    return account


@router.post("/publish/accounts/{account_id}/recheck", response_model=PublishAccountOut)
def recheck_account(account_id: str, db: DbSession, user: CurrentUser) -> PublishAccount:
    """把账号标记为待复检:执行器的下一次巡检立刻认领它重测登录态。"""
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    account.binding_status = "unknown"
    account.last_checked_at = None
    account.last_error = None
    db.commit()
    db.refresh(account)
    return account


@router.delete("/publish/accounts/{account_id}", status_code=204)
def delete_account(account_id: str, db: DbSession, user: CurrentUser) -> Response:
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    db.delete(account)
    db.commit()
    return Response(status_code=204)


@router.get("/publish/tasks", response_model=list[PublishTaskOut])
def list_publish_tasks(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    return [task_with_status(db, task) for task in list_tasks(db, workspace_id)]


@router.post("/publish/tasks", response_model=PublishTaskOut)
def create_publish_task(body: PublishCreate, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "publish")
    account = db.get(PublishAccount, body.account_id)
    if account is None or account.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="Account not found in this workspace")
    asset = db.get(Asset, body.asset_id)
    if asset is None or asset.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="Asset not found in this workspace")
    try:
        task = start_publish(
            db,
            workspace_id=body.workspace_id,
            account=account,
            asset=asset,
            title=body.title,
            description=body.description,
            tags=body.tags,
            created_by=user.id,
            short_title=body.short_title,
        )
    except PublishDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return task_with_status(db, task)


@router.delete("/publish/tasks/{task_id}", status_code=204)
def delete_publish_task(task_id: str, db: DbSession, user: CurrentUser) -> Response:
    task = db.get(PublishTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Publish task not found")
    ensure_workspace_perm(db, user, task.workspace_id, "publish")
    db.delete(task)
    db.commit()
    return Response(status_code=204)


@router.post("/publish/copy", response_model=PublishCopyResponse)
def generate_publish_copy(body: PublishCopyRequest, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "publish")
    from app.domain.publish.copy import generate_copy

    try:
        return generate_copy(
            db,
            user_id=user.id, workspace_id=body.workspace_id, asset_id=body.asset_id, brief=body.brief, profile_id=body.profile_id
        )
    except PublishDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
