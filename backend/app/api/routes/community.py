"""社区账号(ADR 0026 §3「桌面应用」):连不连、连的是谁、连接(设备授权)与断开。

**这组路由只作用在「我自己的社区账号」上** —— 不属于任何工作区,判据是登录的这个人本身。
刷新令牌永远不出这一层:回包里只有 @handle 和昵称。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import CommunityDeviceOut, CommunityPollOut, CommunityStatusOut
from app.domain.community import CommunityError, accounts, device

router = APIRouter(tags=["community"])


def community_http_error(exc: CommunityError) -> HTTPException:
    """社区的错误 → HTTP。**不会是 401**(见 domain/community/errors):那个码在前端的意思是「本机登录过期」。"""
    return HTTPException(status_code=exc.http_status, detail=str(exc))


def _pending(user_id: str) -> CommunityDeviceOut | None:
    flow = device.pending(user_id)
    if flow is None:
        return None
    return CommunityDeviceOut(
        user_code=flow.user_code,
        verification_uri=flow.verification_uri,
        expires_in=max(0, int(flow.expires_at - accounts.clock())),
    )


def community_status(db: DbSession, user_id: str) -> CommunityStatusOut:
    return CommunityStatusOut(**accounts.status(db, user_id), pending=_pending(user_id))


@router.get("/community/status", response_model=CommunityStatusOut)
def get_status(db: DbSession, user: CurrentUser) -> CommunityStatusOut:
    return community_status(db, user.id)


@router.post("/community/connect", response_model=CommunityDeviceOut)
def connect(db: DbSession, user: CurrentUser) -> CommunityDeviceOut:
    """开始连接:向社区要一个设备码。界面拿 `verification_uri` 去系统浏览器里打开,然后轮询。"""
    try:
        flow = device.start(db, user.id)
    except CommunityError as exc:
        raise community_http_error(exc) from exc
    return CommunityDeviceOut(
        user_code=flow.user_code,
        verification_uri=flow.verification_uri,
        expires_in=max(0, int(flow.expires_at - accounts.clock())),
    )


@router.post("/community/connect/poll", response_model=CommunityPollOut)
def poll(db: DbSession, user: CurrentUser) -> CommunityPollOut:
    """问一次「网页上点了允许没有」。按社区给的间隔节流 —— 界面轮询得再勤,真正发出去的请求也不会更多。"""
    try:
        state = device.poll(user.id)
    except CommunityError as exc:
        raise community_http_error(exc) from exc
    return CommunityPollOut(state=state, status=community_status(db, user.id))


@router.delete("/community/connect", status_code=204)
def cancel_connect(user: CurrentUser) -> Response:
    device.cancel(user.id)
    return Response(status_code=204)


@router.post("/community/disconnect", status_code=204)
def disconnect(db: DbSession, user: CurrentUser) -> Response:
    """断开:请社区吊销这台设备的会话(尽力而为),再删掉本机存的令牌。"""
    accounts.disconnect(db, user.id)
    return Response(status_code=204)
