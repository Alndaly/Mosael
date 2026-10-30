"""MosaelCloud 的本地入口:**登录 / 登出 / 我 / 社区分享与通知的全量反代**。

桌面端打的是本机后端,而 Cloud 只接受官网同源、不开 CORS —— 没有这一层,真机上既登不进
MosaelCloud,也打不开社区分享。这一层做两件事:

1. **登录成功时用云端会话换一枚设备令牌,存进本地 `cloud_login`**(按本地用户一行、密文列;ADR 0088),
   之后的每一次转发带 `Authorization: Bearer`;渲染层只拿到 `{email}`,**看不到令牌**;
2. 把 Cloud 的响应原样交回去(状态码、JSON 逐字段),4xx 的文案按请求方的语言挑一句给人看。

云端 401 = 那枚令牌已经被吊销:清掉本地那一行,把 401 交回去,让界面回到"要重新登录"。
Cloud 的地址、客户端、超时、同源头与身份头都在 `domain/cloud_binding` 里,这里只做转发。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Path, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import CloudCodeIn, CloudConnectionSyncOut, CloudOrderIn, CloudEmailIn, CloudLoginIn, CloudMfaCodeIn, CloudMfaRequiredOut, CloudMfaVerifyIn, CloudPasswordIn, CloudPhoneCodeIn, CloudPhoneIn, CloudPhoneLoginIn, CloudSessionOut
from app.core.i18n import get_current_locale, tr
from mosael_formats.i18n import pick_text
from app.db.models import CloudLogin, User
from app.domain import cloud_binding, cloud_connection

router = APIRouter(tags=["cloud"])
logger = logging.getLogger(__name__)

#: 社区分享 / 评论 id 的形状(外部输入):Cloud 的 id 是短 token,这里只收一个路径段能装下的字符。
#: **先过这一道再拼进 URL** —— 不把用户给的东西直接接到云地址后面。
SHARE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ShareId = Annotated[str, Path(pattern=SHARE_ID_PATTERN, description="MosaelCloud 社区分享 id")]
CommentId = Annotated[str, Path(pattern=SHARE_ID_PATTERN, description="MosaelCloud 社区评论 id")]
Handle = Annotated[str, Path(pattern=SHARE_ID_PATTERN, description="MosaelCloud 用户短名")]

#: 同一个部署没接 Cloud、连不上 Cloud 时,界面看到的是这三句。
_CLOUD_UNREACHABLE = {"code": "cloud_unreachable", "message": "Can't reach MosaelCloud. Check the network and try again."}
_CLOUD_TIMEOUT = {"code": "cloud_timeout", "message": "MosaelCloud took too long to answer. Try again in a moment."}
_CLOUD_UPSTREAM_ERROR = {
    "code": "cloud_upstream_error",
    "message": "MosaelCloud returned a server error. Try again in a moment.",
}


def _http_error(error: cloud_binding.CloudBindingError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message})


def _not_signed_in() -> HTTPException:
    """本地没有云端会话(或者云端刚说它没了)。界面据此回到登录表单。"""
    return HTTPException(
        401, detail={"code": "not_authenticated", "message": tr("routeErr_cloudSignInRequired")}
    )


def _cloud_detail(reply: cloud_binding.CloudReply) -> HTTPException:
    """Cloud 4xx 的那句人话。**文案原样转述**,不把 code 丢给用户自己猜。

    Cloud 的 `message` 是中英两份(`cloud/errors.py`),按这次请求的 Accept-Language 挑一条。
    """
    if reply.status >= 500:
        return HTTPException(
            status_code=502, detail={**_CLOUD_UPSTREAM_ERROR, "upstream_status": reply.status}
        )
    body = reply.body if isinstance(reply.body, dict) else {}
    code = str(body.get("error") or "cloud_error")
    message = body.get("message")
    if isinstance(message, dict):
        message = pick_text(message, get_current_locale())
    if not isinstance(message, str) or not message.strip():
        message = tr("routeErr_cloudRejected")
    return HTTPException(status_code=reply.status, detail={"code": code, "message": message})


def _success(reply: cloud_binding.CloudReply) -> Response:
    """2xx 原样交出去。204 没响应体,不能塞一个 `{}` 进去。"""
    if reply.status == 204:
        return Response(status_code=204)
    if 200 <= reply.status < 300:
        return JSONResponse(content=reply.body, status_code=reply.status)
    raise _cloud_detail(reply)


def _send(
    method: str,
    path: str,
    payload: dict | list | None,
    *,
    user: User,
    db: DbSession,
) -> tuple[cloud_binding.CloudReply, CloudLogin | None]:
    """一次带身份的转发:自动带上本地存着的设备令牌,把转发层的异常翻成本地状态码。"""
    row = _load_login(db, user.id)
    try:
        reply = cloud_binding.request_json(
            method, path, payload, device_token=cloud_binding.device_token_of(row)
        )
    except cloud_binding.CloudTimeout as exc:
        raise HTTPException(status_code=504, detail=_CLOUD_TIMEOUT) from exc
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        raise _http_error(exc) from exc
    return reply, row


def _session_relay(
    method: str,
    path: str,
    payload: dict | list | None,
    *,
    user: User,
    db: DbSession,
) -> Response:
    """一条**登录后**的转发:云端 401 就清掉本地那一行,再把 401 交回去。"""
    reply, row = _send(method, path, payload, user=user, db=db)
    if reply.status == 401:
        cloud_binding.drop_login(db, user.id)
        db.commit()
        raise _cloud_detail(reply) if isinstance(reply.body, dict) and reply.body.get("message") else _not_signed_in()
    return _success(reply)


def _ensure_configured() -> None:
    try:
        cloud_binding.require_configured()
    except cloud_binding.CloudBindingError as exc:
        raise _http_error(exc) from exc


def _with_query(path: str, request: Request) -> str:
    """查询串原样带走(搜索词、游标、每页几条都在里面)。"""
    query = request.url.query
    return f"{path}?{query}" if query else path


# ---------------------------------------------------------------- 登录 / 登出 / 我


def _load_login(db: DbSession, user_id: str) -> CloudLogin | None:
    return cloud_binding.load_login(db, user_id)


def _has_password(reply: cloud_binding.CloudReply) -> bool:
    body = reply.body if isinstance(reply.body, dict) else {}
    user = body.get("user") if isinstance(body.get("user"), dict) else {}
    return bool(user.get("has_password"))


def _remember_or_challenge(
    db: DbSession, user: User, email: str, reply: cloud_binding.CloudReply
) -> CloudSessionOut | CloudMfaRequiredOut:
    """主认证成功:开了 MFA 就原样把票据交给桌面端,不落设备令牌。"""
    body = reply.body if isinstance(reply.body, dict) else {}
    if body.get("mfa_required") is True:
        return CloudMfaRequiredOut(
            mfa_required=True,
            ticket=str(body.get("ticket") or ""),
            methods=[str(one) for one in body.get("methods", []) if isinstance(one, str)],
        )
    return _remember(db, user, email, reply)


def _remember(db: DbSession, user: User, email: str, reply: cloud_binding.CloudReply) -> CloudSessionOut:
    """登录成功才走到这里:拿会话换设备令牌、存令牌、回邮箱。**cookie 与令牌都不出这个函数**。"""
    if reply.cookie is None:
        # Cloud 说成功却没下发会话 cookie —— 那是它的故障,不是"登录成功了但没身份"。
        raise HTTPException(
            status_code=502, detail={**_CLOUD_UPSTREAM_ERROR, "upstream_status": reply.status}
        )
    try:
        token = cloud_binding.exchange_for_device_token(reply.cookie)
    except cloud_binding.CloudTimeout as exc:
        raise HTTPException(status_code=504, detail=_CLOUD_TIMEOUT) from exc
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        raise _http_error(exc) from exc
    if token is None:
        # 登录成功了却换不到令牌 —— 同样是 Cloud 那边的故障;本地什么都不存,用户再登一次即可。
        raise HTTPException(status_code=502, detail=_CLOUD_UPSTREAM_ERROR)
    canonical = email.strip().lower()
    cloud_binding.save_login(db, user.id, email=canonical, token=token)
    db.commit()
    _sync_connection_quietly(db, user)
    return CloudSessionOut(email=canonical, has_password=_has_password(reply))


def _sync_connection_quietly(db: DbSession, user: User) -> None:
    """登录之后把「Mosael Cloud」连接与网关目录对齐(ADR 0088)。**对不齐不让登录失败**:网关一时不可用、这个部署的 Cloud
    还没有网关,登录本身照样成功;连接那一行有「刷新」,之后再对。"""
    try:
        cloud_connection.sync(db, user.id)
        db.commit()
    except (cloud_binding.CloudUnavailable, cloud_binding.CloudBindingError) as exc:
        db.rollback()
        logger.warning("登录 MosaelCloud 之后没能对齐网关目录:%s", exc)


@router.post("/cloud/v1/login", response_model=CloudSessionOut | CloudMfaRequiredOut, response_model_exclude_defaults=True)
def login(body: CloudLoginIn, user: CurrentUser, db: DbSession) -> CloudSessionOut | CloudMfaRequiredOut:
    """邮箱 + 密码登录。**密码只活在这一跳里**:不落库、不进日志、不进响应。"""
    reply, _row = _send(
        "POST", "/login", {"email": body.email, "password": body.password}, user=user, db=db
    )
    if reply.status != 200:
        raise _cloud_detail(reply)
    return _remember_or_challenge(db, user, body.email, reply)


@router.post("/cloud/v1/login/phone", response_model=CloudSessionOut | CloudMfaRequiredOut, response_model_exclude_defaults=True)
def login_with_phone(body: CloudPhoneLoginIn, user: CurrentUser, db: DbSession) -> CloudSessionOut | CloudMfaRequiredOut:
    """手机号 + 密码登录。Cloud 校验手机号与密码,本地照样换设备令牌、只回登录标识。"""
    reply, _row = _send(
        "POST",
        "/login/phone",
        {"phone": body.phone, "password": body.password},
        user=user,
        db=db,
    )
    if not 200 <= reply.status < 300:
        raise _cloud_detail(reply)
    return _remember_or_challenge(db, user, body.phone, reply)


@router.post("/cloud/v1/login/code")
def send_login_code(body: CloudEmailIn, user: CurrentUser, db: DbSession) -> Response:
    """验证码登录第一步:让 Cloud 把 6 位码发到这个邮箱。"""
    reply, _row = _send("POST", "/login/code", {"email": body.email}, user=user, db=db)
    return _success(reply)


@router.post("/cloud/v1/login/code/verify", response_model=CloudSessionOut | CloudMfaRequiredOut, response_model_exclude_defaults=True)
def verify_login_code(body: CloudCodeIn, user: CurrentUser, db: DbSession) -> CloudSessionOut | CloudMfaRequiredOut:
    """验证码登录第二步:码换会话。和密码登录落库的形状完全一样。"""
    reply, _row = _send(
        "POST", "/login/code/verify", {"email": body.email, "code": body.code}, user=user, db=db
    )
    if reply.status != 200:
        raise _cloud_detail(reply)
    return _remember_or_challenge(db, user, body.email, reply)


@router.post("/cloud/v1/login/sms/code")
def send_login_sms_code(body: CloudPhoneIn, user: CurrentUser, db: DbSession) -> Response:
    """短信登录第一步:让 Cloud 发短信验证码。"""
    reply, _row = _send("POST", "/login/sms/code", {"phone": body.phone}, user=user, db=db)
    return _success(reply)


@router.post("/cloud/v1/login/sms/verify", response_model=CloudSessionOut | CloudMfaRequiredOut, response_model_exclude_defaults=True)
def verify_login_sms(body: CloudPhoneCodeIn, user: CurrentUser, db: DbSession) -> CloudSessionOut | CloudMfaRequiredOut:
    """短信登录第二步。Cloud 在首次验证时会自动建手机号账号。"""
    reply, _row = _send(
        "POST", "/login/sms/verify", {"phone": body.phone, "code": body.code}, user=user, db=db
    )
    if reply.status != 200:
        raise _cloud_detail(reply)
    return _remember_or_challenge(db, user, body.phone, reply)


@router.post("/cloud/v1/me/password", response_model=CloudSessionOut, response_model_exclude_defaults=True)
def change_cloud_password(body: CloudPasswordIn, user: CurrentUser, db: DbSession) -> CloudSessionOut:
    """设置 / 修改云端密码。已有密码时必须带当前密码;新密码由 Cloud 按同一套长度策略校验。"""
    reply, _row = _send(
        "POST",
        "/me/password",
        {"current_password": body.current_password, "new_password": body.new_password},
        user=user,
        db=db,
    )
    if not 200 <= reply.status < 300:
        raise _cloud_detail(reply)
    row = _load_login(db, user.id)
    if row is None:
        raise _not_signed_in()
    return CloudSessionOut(email=row.email, has_password=True)


@router.post("/cloud/v1/logout", status_code=204)
def logout(user: CurrentUser, db: DbSession) -> Response:
    """退出桌面端的云端登录:让 Cloud 吊销这枚设备令牌,再删本地那一行。

    **本地一定要退得掉**:Cloud 不可达时照样删本地那一行(令牌留在官网「我的设备」里,可以在那里删),
    不让"断网"变成"退不出去"。没登录过就是一次幂等的 204。
    """
    _ensure_configured()
    row = _load_login(db, user.id)
    if row is None:
        return Response(status_code=204)
    try:
        _send("DELETE", "/device-tokens/current", None, user=user, db=db)
    finally:
        cloud_binding.drop_login(db, user.id)
        db.commit()
    return Response(status_code=204)


@router.post("/cloud/v1/connection/sync", response_model=CloudConnectionSyncOut)
def sync_connection(user: CurrentUser, db: DbSession) -> CloudConnectionSyncOut:
    """「Mosael Cloud」连接上的「刷新」:重新问网关要模型清单和积分单价。没登录 401;令牌被吊销清掉本地登录、401。"""
    _ensure_configured()
    try:
        synced = cloud_connection.sync(db, user.id)
    except cloud_binding.CloudTimeout as exc:
        raise HTTPException(status_code=504, detail=_CLOUD_TIMEOUT) from exc
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        db.commit()
        raise _http_error(exc) from exc
    db.commit()
    return CloudConnectionSyncOut(profile_id=synced.profile.id, models=synced.models)


@router.get("/cloud/v1/gateway/account")
def gateway_account(user: CurrentUser, db: DbSession) -> Response:
    """这个人在官方中转上的积分(按批次、先到期在前)、下一批何时发、套餐 —— 照 Cloud 的原样交回。"""
    _ensure_configured()
    if _load_login(db, user.id) is None:
        raise _not_signed_in()
    return _session_relay("GET", "/gateway/account", None, user=user, db=db)


@router.post("/cloud/v1/mfa/verify", response_model=CloudSessionOut, response_model_exclude_defaults=True)
def verify_cloud_mfa(body: CloudMfaVerifyIn, user: CurrentUser, db: DbSession) -> CloudSessionOut:
    """双因素登录第二步:票据 + 验证码/恢复码换设备令牌。"""
    reply, _row = _send(
        "POST", "/mfa/verify", {"ticket": body.ticket, "code": body.code}, user=user, db=db
    )
    if not 200 <= reply.status < 300:
        raise _cloud_detail(reply)
    payload = reply.body if isinstance(reply.body, dict) else {}
    account = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    label = str(account.get("email") or account.get("phone") or "")
    return _remember(db, user, label, reply)


@router.get("/cloud/v1/mfa")
def cloud_mfa_status(user: CurrentUser, db: DbSession) -> Response:
    _ensure_configured()
    return _session_relay("GET", "/mfa", None, user=user, db=db)


@router.post("/cloud/v1/mfa/setup")
def cloud_mfa_setup(user: CurrentUser, db: DbSession) -> Response:
    reply, _row = _send("POST", "/mfa/setup", None, user=user, db=db)
    return _success(reply)


@router.post("/cloud/v1/mfa/enable")
def cloud_mfa_enable(body: CloudMfaCodeIn, user: CurrentUser, db: DbSession) -> Response:
    reply, _row = _send("POST", "/mfa/enable", {"code": body.code}, user=user, db=db)
    return _success(reply)


@router.post("/cloud/v1/mfa/disable")
def cloud_mfa_disable(body: CloudMfaCodeIn, user: CurrentUser, db: DbSession) -> Response:
    reply, _row = _send("POST", "/mfa/disable", {"code": body.code}, user=user, db=db)
    return _success(reply)


@router.post("/cloud/v1/mfa/recovery-codes")
def cloud_mfa_recovery_codes(body: CloudMfaCodeIn, user: CurrentUser, db: DbSession) -> Response:
    reply, _row = _send("POST", "/mfa/recovery-codes", {"code": body.code}, user=user, db=db)
    return _success(reply)


@router.get("/cloud/v1/me", response_model=CloudSessionOut, response_model_exclude_defaults=True)
def me(user: CurrentUser, db: DbSession) -> CloudSessionOut:
    """「现在登的是谁」。没登录 → 401(界面据此显示登录表单);令牌被吊销 → 清行 + 401。"""
    _ensure_configured()
    row = _load_login(db, user.id)
    if row is None:
        raise _not_signed_in()
    reply, _row = _send("GET", "/me", None, user=user, db=db)
    if reply.status == 401:
        cloud_binding.drop_login(db, user.id)
        db.commit()
        raise _not_signed_in()
    if not 200 <= reply.status < 300:
        raise _cloud_detail(reply)
    #: 登录标识取本地那一行;密码状态从 Cloud 当前账号读。
    return CloudSessionOut(email=row.email, has_password=_has_password(reply))


# ---------------------------------------------------------------- 社区分享:公开读(带上身份)


def _relay(status: int, body: dict | list) -> JSONResponse:
    """把 Cloud 的回答**原样**交出去:状态码是它的,JSON 也逐字段是它的。

    4xx(404 / 413 / 422)尤其不翻译 ——「这份分享不存在」是界面照着 404 说的话;后端替它翻译,
    两边的码和文案就会各说一套。5xx 是唯一的例外:那是 Cloud 自己的故障,对本地调用方是 502。
    """
    if status >= 500:
        raise HTTPException(status_code=502, detail={**_CLOUD_UPSTREAM_ERROR, "upstream_status": status})
    return JSONResponse(content=body, status_code=status)


def _forward(call: Callable[[], tuple[int, dict | list]]) -> JSONResponse:
    """一次转发的统一出口:慢 → 504,到不了 → 503,没配 → 503,5xx → 502。"""
    try:
        status, body = call()
    except cloud_binding.CloudTimeout as exc:
        raise HTTPException(status_code=504, detail=_CLOUD_TIMEOUT) from exc
    except cloud_binding.CloudUnavailable as exc:
        raise HTTPException(status_code=503, detail=_CLOUD_UNREACHABLE) from exc
    except cloud_binding.CloudBindingError as exc:
        raise _http_error(exc) from exc
    return _relay(status, body)


def _public_read(user: User, db: DbSession, path: str) -> JSONResponse:
    """公开读:**登录了就以登录身份读**(点赞 / 收藏的"我"才对得上),没登录就按游客读。"""
    device_token = cloud_binding.device_token_of(_load_login(db, user.id))

    def call() -> tuple[int, dict | list]:
        reply = cloud_binding.request_json("GET", path, device_token=device_token)
        return reply.status, reply.body

    return _forward(call)


@router.get("/cloud/v1/shares/{share_id}")
def get_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> JSONResponse:
    """分享详情。登录之后自动带上身份(游客也照常读)。"""
    return _public_read(user, db, f"/shares/{share_id}")


@router.get("/cloud/v1/shares/{share_id}/payload")
def get_community_share_payload(share_id: ShareId, user: CurrentUser, db: DbSession) -> JSONResponse:
    """分享内容本体。响应就是 Cloud 的 `{"payload": …}`,这里不拆、不校验。"""
    return _public_read(user, db, f"/shares/{share_id}/payload")


# ---------------------------------------------------------------- 社区分享:列表 / 发布 / 点赞 / 评论


@router.get("/cloud/v1/shares")
def browse_community_shares(request: Request, user: CurrentUser, db: DbSession) -> Response:
    """社区分享列表(搜索 / 排序 / 游标都由 Cloud 解释)。"""
    return _session_relay("GET", _with_query("/shares", request), None, user=user, db=db)


@router.post("/cloud/v1/shares", status_code=201)
def publish_community_share(user: CurrentUser, db: DbSession, body: dict = Body(...)) -> Response:
    """发布一份分享。请求体原样转给 Cloud,由它校验。"""
    return _session_relay("POST", "/shares", body, user=user, db=db)


@router.delete("/cloud/v1/shares/{share_id}")
def delete_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("DELETE", f"/shares/{share_id}", None, user=user, db=db)


@router.post("/cloud/v1/shares/{share_id}/download")
def download_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    """下载一次。Cloud 那侧会**把 downloads +1**,所以方法必须是 POST —— 别顺手改成 GET。"""
    return _session_relay("POST", f"/shares/{share_id}/download", {}, user=user, db=db)


@router.post("/cloud/v1/shares/{share_id}/like", status_code=204)
def like_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("POST", f"/shares/{share_id}/like", {}, user=user, db=db)


@router.delete("/cloud/v1/shares/{share_id}/like", status_code=204)
def unlike_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("DELETE", f"/shares/{share_id}/like", None, user=user, db=db)


@router.post("/cloud/v1/shares/{share_id}/favorite", status_code=204)
def favorite_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("POST", f"/shares/{share_id}/favorite", {}, user=user, db=db)


@router.delete("/cloud/v1/shares/{share_id}/favorite", status_code=204)
def unfavorite_community_share(share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("DELETE", f"/shares/{share_id}/favorite", None, user=user, db=db)


@router.get("/cloud/v1/shares/{share_id}/comments")
def list_community_comments(request: Request, share_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("GET", _with_query(f"/shares/{share_id}/comments", request), None, user=user, db=db)


@router.post("/cloud/v1/shares/{share_id}/comments", status_code=201)
def add_community_comment(
    share_id: ShareId, user: CurrentUser, db: DbSession, body: dict = Body(...)
) -> Response:
    return _session_relay("POST", f"/shares/{share_id}/comments", body, user=user, db=db)


@router.delete("/cloud/v1/shares/{share_id}/comments/{comment_id}", status_code=204)
def delete_community_comment(
    share_id: ShareId, comment_id: CommentId, user: CurrentUser, db: DbSession
) -> Response:
    return _session_relay(
        "DELETE", f"/shares/{share_id}/comments/{comment_id}", None, user=user, db=db
    )


@router.get("/cloud/v1/users/{handle}/shares")
def community_user_shares(request: Request, handle: Handle, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("GET", _with_query(f"/users/{handle}/shares", request), None, user=user, db=db)


# ---------------------------------------------------------------- 通知


@router.get("/cloud/v1/notifications")
def list_cloud_notifications(request: Request, user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("GET", _with_query("/notifications", request), None, user=user, db=db)


@router.get("/cloud/v1/notifications/unread-count")
def count_unread_cloud_notifications(user: CurrentUser, db: DbSession) -> Response:
    return _session_relay("GET", "/notifications/unread-count", None, user=user, db=db)


@router.post("/cloud/v1/notifications/read")
def mark_cloud_notifications_read(
    user: CurrentUser, db: DbSession, body: dict = Body(default_factory=dict)
) -> Response:
    return _session_relay("POST", "/notifications/read", body, user=user, db=db)


# ---------------------------------------------------------------- 在线购买(ADR 0088 第 3 步)


@router.get("/cloud/v1/plans")
def list_cloud_plans(user: CurrentUser, db: DbSession) -> JSONResponse:
    """在线能买的套餐、这个部署开了哪些支付渠道。公开读,照 Cloud 的原样交回。"""
    return _public_read(user, db, "/plans")


@router.post("/cloud/v1/orders", status_code=201)
def create_cloud_order(body: CloudOrderIn, user: CurrentUser, db: DbSession) -> Response:
    """下单拿二维码。要先登录 MosaelCloud(用这台设备的令牌下单)。"""
    _ensure_configured()
    if _load_login(db, user.id) is None:
        raise _not_signed_in()
    return _session_relay("POST", "/orders", body.model_dump(), user=user, db=db)


@router.get("/cloud/v1/orders/{order_id}")
def get_cloud_order(order_id: ShareId, user: CurrentUser, db: DbSession) -> Response:
    """订单状态。桌面端扫码后轮询它;还没到账时 Cloud 会顺手问一次支付渠道。"""
    _ensure_configured()
    if _load_login(db, user.id) is None:
        raise _not_signed_in()
    return _session_relay("GET", f"/orders/{order_id}", None, user=user, db=db)
