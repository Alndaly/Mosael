from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, PresentedToken
from app.api.schemas import ConfirmationCreate, ConfirmationOut
from app.core.permissions import ensure_workspace_access
from app.db.models import AuthSession, ToolConfirmation
from app.integrations.feishu.service import announce_confirmation
from app.domain.agent.confirmations import (
    ConfirmationError,
    authorize_and_approve,
    authorize_and_reject,
    request_confirmation,
)

router = APIRouter(tags=["confirmations"])


@router.post("/confirmations", response_model=ConfirmationOut)
def create_confirmation(
    body: ConfirmationCreate, db: DbSession, user: CurrentUser, token: PresentedToken
) -> ToolConfirmation:
    ensure_workspace_access(db, user, body.workspace_id)
    # 归属**由凭据决定**,不由请求体声明。一次 turn 一个令牌,铸的时候正好知道是哪次对话;调用方
    # 转述的话就可以被伪造 —— 任何拿着同一份凭据的通道,填上别人的会话 id 就能把自己的动作挂进
    # 那次对话(三档权限模式下,那等于挂进别人开的自动放行)。没有会话的凭据(登录令牌、MCP 直连)
    # 开出来的卡就是无主的,由全局确认中心兜底。
    auth = db.get(AuthSession, token)
    try:
        confirmation = request_confirmation(
            db,
            workspace_id=body.workspace_id,
            tool=body.tool,
            payload=body.payload,
            requested_by=body.requested_by,
            session_id=auth.agent_session_id if auth is not None else None,
        )
    except ConfirmationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 把新卡推到它该出现的地方(目前只有飞书:从飞书驱动的会话,卡片应当回到那个飞书会话)。
    #
    # 放在**路由层**而不是领域层:领域回调集成层会形成 confirmations ⇄ feishu.service 的循环
    # 依赖,只能靠函数内延迟导入绕开。路由是组合层,认识集成层是它的本分。request_confirmation
    # 全项目只有这一个调用方,所以挪上来覆盖面一点不减。
    announce_confirmation(db, confirmation)
    return confirmation


@router.get("/confirmations", response_model=list[ConfirmationOut])
def list_confirmations(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    limit: int = 30,
    session_id: str | None = None,
    unowned: bool = False,
) -> list[ToolConfirmation]:
    """待确认列表。

    确认卡按**发起会话**归属:
      - `session_id=X` —— 只要该会话的卡。聊天里的内联确认卡用这个,否则同工作区其它对话、
        工作流节点、外部智能体的卡都会挤进当前对话,更糟的是会被这边的「本会话始终允许」
        自动批准(授权范围逃逸)。
      - `unowned=true` —— 只要**没有会话**的卡(MCP / 飞书等外部智能体)。全局确认中心用这个。
      - 都不传 —— 全部,供调试/审计。
    """
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(ToolConfirmation).where(ToolConfirmation.workspace_id == workspace_id)
    if session_id:
        stmt = stmt.where(ToolConfirmation.session_id == session_id)
    elif unowned:
        stmt = stmt.where(ToolConfirmation.session_id.is_(None))
    if status:
        stmt = stmt.where(ToolConfirmation.status == status)
    stmt = stmt.order_by(ToolConfirmation.created_at.desc()).limit(min(limit, 100))
    return list(db.scalars(stmt))


@router.get("/confirmations/{confirmation_id}", response_model=ConfirmationOut)
def get_confirmation(confirmation_id: str, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    confirmation = _require(db, user, confirmation_id)
    return confirmation


# 路由这一层只做两件事:认身份(CurrentUser)、把领域异常翻译成 HTTP 码。
# 「能不能批、批了会发生什么」在 domain/agent/confirmations.authorize_and_* 里,
# 和飞书卡片那条入口共用同一份 —— 校验规则不该按入口各写一遍。
@router.post("/confirmations/{confirmation_id}/approve", response_model=ConfirmationOut)
def approve(confirmation_id: str, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    confirmation = _get_or_404(db, confirmation_id)
    try:
        return authorize_and_approve(db, user, confirmation)
    except ConfirmationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/confirmations/{confirmation_id}/reject", response_model=ConfirmationOut)
def reject(confirmation_id: str, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    confirmation = _get_or_404(db, confirmation_id)
    try:
        return authorize_and_reject(db, user, confirmation)
    except ConfirmationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _get_or_404(db: DbSession, confirmation_id: str) -> ToolConfirmation:
    """只管存在性。归属校验交给调用方 —— 读走 _require,写走 authorize_and_*。"""
    confirmation = db.get(ToolConfirmation, confirmation_id)
    if confirmation is None:
        raise HTTPException(status_code=404, detail="Not found")
    return confirmation


def _require(db: DbSession, user: CurrentUser, confirmation_id: str) -> ToolConfirmation:
    confirmation = _get_or_404(db, confirmation_id)
    ensure_workspace_access(db, user, confirmation.workspace_id)
    return confirmation
