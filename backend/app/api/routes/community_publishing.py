"""往社区**发东西**(ADR 0026 §4、§5、ADR 0027 §4):画板分享、工作流发布、插件发布、资产分享。

和 `community.py`(我自己的账号)分开放,因为这里的每一条都作用在**某个工作区的东西**上,各自点名权限:
画板和工作流要这个工作区的编辑权限(分享 / 发布是对外的动作,只读成员不该能做);插件是部署级的,
要部署管理员(和装、卸插件同一道闸)。发出去用的是**点按钮的这个人**自己的社区账号。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from app.core.i18n import tr
from app.api.routes.community import community_http_error, community_status
from app.api.schemas import (
    BoardShareIn,
    BoardShareOut,
    BoardShareStateOut,
    BoardShareUpdate,
    CommunityAssetPageOut,
    CommunityPublishOut,
    EntityCommunityOut,
    EntityCommunityPublishedOut,
    EntityPublishIn,
    JobOut,
    PluginPublishIn,
    WorkflowPublishIn,
)
from app.db.models import Board, Entity, Job, PluginPackage, Workflow
from app.domain.boards import BoardDomainError, get_board
from app.domain.community import CommunityError, publish, shares
from app.domain.community import assets as community_assets
from app.domain.entities.library import EntityNotFound, entity_workspace, get_entity
from app.domain.permissions import ensure_deployment_admin, ensure_workspace_access, ensure_workspace_perm

router = APIRouter(tags=["community"])


def _board(db: DbSession, workspace_id: str, board_id: str) -> Board:
    try:
        return get_board(db, workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/boards/{board_id}/share", response_model=BoardShareStateOut)
def board_share_state(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> BoardShareStateOut:
    """分享面板一打开要的:这张板分享过没有(链接、第几版),以及这个人连没连社区。"""
    ensure_workspace_access(db, user, workspace_id)
    board = _board(db, workspace_id, board_id)
    row = shares.current(db, board)
    return BoardShareStateOut(
        share=BoardShareOut.model_validate(row) if row is not None else None,
        status=community_status(db, user.id),
    )


@router.post("/boards/{board_id}/share", response_model=JobOut)
def share_board(board_id: str, body: BoardShareIn, db: DbSession, user: CurrentUser) -> Job:
    """生成链接 / 更新分享(同一件事:服务端按画板认出新版本,链接不变)。排成任务,进度在任务中心。"""
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    board = _board(db, body.workspace_id, board_id)
    try:
        return shares.start(db, board=board, user_id=user.id, title=body.title, visibility=body.visibility)
    except CommunityError as exc:
        raise community_http_error(exc) from exc


@router.patch("/boards/{board_id}/share", response_model=BoardShareOut)
def update_board_share(board_id: str, body: BoardShareUpdate, db: DbSession, user: CurrentUser) -> object:
    """改分享的标题 / 可见性,不发新版本。"""
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    board = _board(db, body.workspace_id, board_id)
    try:
        return shares.update(db, board=board, user_id=user.id, title=body.title, visibility=body.visibility)
    except CommunityError as exc:
        raise community_http_error(exc) from exc


@router.delete("/boards/{board_id}/share", status_code=204)
def withdraw_board_share(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> Response:
    """撤回:链接立刻失效(服务端回 410),本机忘掉这条分享。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    board = _board(db, workspace_id, board_id)
    try:
        shares.withdraw(db, board=board, user_id=user.id)
    except CommunityError as exc:
        raise community_http_error(exc) from exc
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/community", response_model=CommunityPublishOut)
def publish_workflow(
    workflow_id: str, body: WorkflowPublishIn, db: DbSession, user: CurrentUser
) -> CommunityPublishOut:
    """发布到社区:第一次是新条目,之后是这一条的新版本。"""
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    ensure_workspace_perm(db, user, workflow.workspace_id, "edit")
    try:
        result = publish.publish_workflow(
            db,
            workflow=workflow,
            user_id=user.id,
            title=body.title,
            summary=body.summary,
            tags=body.tags,
            cover_asset_id=body.cover_asset_id,
        )
    except CommunityError as exc:
        raise community_http_error(exc) from exc
    return CommunityPublishOut(**result)


@router.post("/plugins/{package_id}/community", response_model=CommunityPublishOut)
def publish_plugin(package_id: str, body: PluginPublishIn, db: DbSession, user: CurrentUser) -> CommunityPublishOut:
    """把一个装着的插件打包发到社区。先进审核队列(回来的状态是 `pending`)。"""
    ensure_deployment_admin(db, user)
    package = db.get(PluginPackage, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail=tr("pluginErr_notFound"))
    try:
        result = publish.publish_plugin(db, package=package, user_id=user.id, summary=body.summary, tags=body.tags)
    except CommunityError as exc:
        raise community_http_error(exc) from exc
    return CommunityPublishOut(**result)


@router.get("/community/assets", response_model=CommunityAssetPageOut)
def browse_community_assets(
    db: DbSession, _user: CurrentUser, q: str = "", asset_kind: str = "", cursor: str = ""
) -> CommunityAssetPageOut:
    """「从社区导入」弹窗里的列表。读的是社区上公开的东西,不需要连账号。"""
    try:
        return CommunityAssetPageOut(**community_assets.browse(db, q=q, asset_kind=asset_kind, cursor=cursor))
    except CommunityError as exc:
        raise community_http_error(exc) from exc


@router.get("/entities/{entity_id}/community", response_model=EntityCommunityOut)
def entity_community(entity_id: str, db: DbSession, user: CurrentUser) -> EntityCommunityOut:
    """资产详情里「社区」那一格:发出去的是哪一条、从哪一条导入的、那一条有没有新版本,以及这个人连没连社区。"""
    entity = _entity_for(db, user, entity_id, perm=None)
    state = community_assets.status(db, entity)
    return EntityCommunityOut(**state, status=community_status(db, user.id))


@router.post("/entities/{entity_id}/community", response_model=EntityCommunityPublishedOut)
def publish_entity(
    entity_id: str, body: EntityPublishIn, db: DbSession, user: CurrentUser
) -> EntityCommunityPublishedOut:
    """把一个资产(连同变体)分享到社区:第一次是新条目,之后是这一条的新版本。真人人物先审核。"""
    entity = _entity_for(db, user, entity_id, perm="edit", workspace_id=body.workspace_id)
    try:
        result = community_assets.publish_entity(
            db,
            entity=entity,
            user_id=user.id,
            consent_confirmed=body.consent_confirmed,
            title=body.title,
            summary=body.summary,
            tags=body.tags,
        )
    except CommunityError as exc:
        raise community_http_error(exc) from exc
    return EntityCommunityPublishedOut(**result)


def _entity_for(
    db: DbSession, user: CurrentUser, entity_id: str, *, perm: str | None, workspace_id: str | None = None
) -> Entity:
    """取资产并过闸。点名了工作区就得对得上 —— 对不上和不存在是同一个答案。"""
    owner = entity_workspace(db, entity_id)
    if workspace_id is not None and workspace_id != owner:
        raise EntityNotFound("entityErr_notFound")
    if perm is None:
        ensure_workspace_access(db, user, owner)
    else:
        ensure_workspace_perm(db, user, owner, perm)
    return get_entity(db, owner, entity_id)
