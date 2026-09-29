from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, PresentedToken
from app.api.schemas import ConfirmationCreate, ConfirmationOut
from app.domain.permissions import ensure_workspace_access
from app.db.models import ToolConfirmation, now
from app.domain.agent import autopilot
from app.domain.agent.sessions import ensure_reads_for, reads_for_filter
from app.domain.agent.confirmations import (
    ConfirmationError,
    authorize_and_approve,
    authorize_and_reject,
    decidable_filter,
)
from app.domain.agent.proposals import propose

router = APIRouter(tags=["confirmations"])


@router.post("/confirmations", response_model=ConfirmationOut)
def create_confirmation(
    body: ConfirmationCreate, db: DbSession, user: CurrentUser, token: PresentedToken
) -> ToolConfirmation:
    """开卡的四步(过闸、建卡、判自动放行、推到原渠道)在 domain/agent/proposals.propose,智能体工具直接调同一个。

    归属**由凭据决定**,不由请求体声明:一次 turn 一个令牌,铸的时候正好知道是哪次对话。没有会话的凭据
    (登录令牌)开出来的卡就是无主的,由全局确认中心兜底。
    """
    try:
        return propose(
            db, user, workspace_id=body.workspace_id, tool=body.tool, payload=body.payload,
            requested_by=body.requested_by, session_id=autopilot.session_for_token(db, token),
        )
    except ConfirmationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/confirmations", response_model=list[ConfirmationOut])
def list_confirmations(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    limit: int = 30,
    session_id: str | None = None,
    unowned: bool = False,
    decidable: bool = False,
) -> list[ToolConfirmation]:
    """他看得见的确认卡。

    一张卡跟着发起它的那次对话走:别人没共享的对话里的卡(工具名、参数)他看不到,和那次对话本身一样
    (判据在 domain/agent/sessions.reads_for_filter;没挂在对话上的、挂在无主的飞书群聊会话上的是工作区的卡)。
      - `session_id=X` —— 只要这次对话的卡,先得看得见这次对话(否则 404)。聊天里的内联确认卡用这个,
        否则同工作区其它对话、工作流节点、外部智能体的卡都会挤进当前对话,更糟的是会被这边的
        「本会话始终允许」自动批准(授权范围逃逸)。
      - `unowned=true` —— 只要**没有会话**的卡(MCP 直连等外部智能体)。
      - `decidable=true` —— 只要**他能拍板**的:列出来的每一张,批 / 拒都不会被权限挡回(判据与批的那一刻
        同一对,见 domain/agent/confirmations.decidable_filter)。全局确认中心用这个 —— 共享来的对话里的卡
        他看得见、批不了,那种卡只在聊天里就地摆着等主人,不该在中心里冒成一张点了就 403 的卡。
      - 都不传 —— 他看得见的全部。
    """
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(ToolConfirmation).where(
        ToolConfirmation.workspace_id == workspace_id,
        reads_for_filter(ToolConfirmation.session_id, user.id, workspace_id),
    )
    if session_id:
        ensure_reads_for(db, session_id, user.id)
        stmt = stmt.where(ToolConfirmation.session_id == session_id)
    elif unowned:
        stmt = stmt.where(ToolConfirmation.session_id.is_(None))
    if decidable:
        stmt = stmt.where(decidable_filter(db, user, workspace_id))
    if status:
        stmt = stmt.where(ToolConfirmation.status == status)
    if status == "pending":
        # 隔离判断者正在看的卡先不显示:它几秒内多半会自己消失(放行了),让用户看见一张自己出现
        # 又自己消失的卡只会造成困惑。期限一过它自动回到这里 —— 不需要任何回收动作。
        stmt = stmt.where(
            or_(ToolConfirmation.hold_until.is_(None), ToolConfirmation.hold_until <= now())
        )
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
    """他看得见的那一张:工作区的人,且看得见卡挂着的那次对话。看不见和不存在同一个回答(404)。"""
    confirmation = _get_or_404(db, confirmation_id)
    ensure_workspace_access(db, user, confirmation.workspace_id)
    ensure_reads_for(db, confirmation.session_id, user.id)
    return confirmation
