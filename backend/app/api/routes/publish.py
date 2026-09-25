from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, Request
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
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Asset, PublishAccount, PublishTask
from app.core.i18n import normalize_locale, t
from app.domain.publish import (
    PUBLISH_PLATFORMS,
    PublishDomainError,
    create_account,
    delete_account,
    list_tasks,
    option_specs,
    recheck_account,
    start_publish,
    task_with_status,
    update_account,
)

router = APIRouter(tags=["publish"])


@router.get("/publish/platforms", response_model=list[PublishPlatformOut])
def platforms(request: Request) -> list[dict]:
    # 目录里存的是 key,**在出口翻译** —— 领域数据不必知道语言(见 core/i18n)。
    locale = normalize_locale(request.headers.get("accept-language"))
    return [
        {
            "platform": key,
            "label": meta["label"],
            "description": t(meta["description"], locale),
            "config": meta["config"],
            "title_max": meta.get("title_max", 300),
            "short_title": meta.get("short_title", False),
            # 平台自己的发布选项:前端照这份**自动**把控件画出来,不为每个平台写一段表单。
            "options": [
                {
                    **spec,
                    "label": t(spec["label"], locale),
                    "description": t(spec["description"], locale) if spec.get("description") else "",
                    "choices": [{**c, "label": t(c["label"], locale)} for c in spec.get("choices", [])],
                }
                for spec in option_specs(key)
            ],
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


def _account(db: DbSession, account_id: str) -> PublishAccount:
    account = db.get(PublishAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.patch("/publish/accounts/{account_id}", response_model=PublishAccountOut)
def update_account_route(account_id: str, body: PublishAccountUpdate, db: DbSession, user: CurrentUser) -> PublishAccount:
    account = _account(db, account_id)
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    try:
        return update_account(db, account, body.model_dump(exclude_unset=True), actor=user.id)
    except sharing.NotManageableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/publish/accounts/{account_id}/recheck", response_model=PublishAccountOut)
def recheck_account_route(account_id: str, db: DbSession, user: CurrentUser) -> PublishAccount:
    """把账号标记为待复检:执行器的下一次巡检立刻认领它重测登录态。"""
    account = _account(db, account_id)
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    try:
        return recheck_account(db, account, actor=user.id)
    except sharing.NotManageableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/publish/accounts/{account_id}", status_code=204)
def delete_account_route(account_id: str, db: DbSession, user: CurrentUser) -> Response:
    account = _account(db, account_id)
    ensure_workspace_perm(db, user, account.workspace_id, "publish")
    try:
        delete_account(db, account, actor=user.id)
    except sharing.NotManageableError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
            actor=user.id,
            short_title=body.short_title,
            options=body.options,
        )
    except sharing.NotUsableError as exc:
        # 别人的私有账号:不是参数错了,是没有这个权限。
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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
