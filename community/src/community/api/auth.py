"""`/auth`:短信 / 密码登录与注册、找回密码、刷新、退出、设备授权(ADR 0026 第 2、3 节)。

「登录」的回包:`{access_token, expires_in, user}`。网页的刷新令牌只在 `Set-Cookie` 里(HttpOnly、SameSite=Lax、
Path 为刷新接口所在的前缀);应用(设备授权、`refresh` 带 body 的那种)在 body 里多一个 `refresh_token`。
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from community.api.deps import Ctx, CurrentUser, Db, client_ip, resolve_principal
from community.api.views import me_user
from community.context import Context
from community.crypto import random_token, sha256_hex
from community.db import utcnow
from community.errors import ApiError
from community.logs import log_event
from community.models import STATUS_ACTIVE, AuthSession, DeviceAuthorization, RateCounter, User
from community.security import (
    check_login_allowed,
    check_password_shape,
    hash_password,
    needs_rehash,
    normalize_handle,
    normalize_phone,
    record_login_failure,
    record_login_success,
    verify_password,
)
from community.sms import PURPOSES, send_code, verify_code
from community.tokens import SESSION_APP, SESSION_WEB, TokenPair, revoke_all, revoke_session, rotate, session_for_refresh, start_session
from mosael_formats.i18n import current_locale

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

#: RFC 8628 建议的用户码字母表:只用辅音字母(不会拼出单词,也没有 0/O、1/I 这类容易看错的)。
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
DEVICE_CODE_TTL_SECONDS = 600
DEVICE_POLL_INTERVAL = 5
DEVICE_CODES_PER_IP_PER_HOUR = 30


# ---------------- 请求体 ----------------


class Captcha(BaseModel):
    ticket: str = Field(max_length=4096)
    randstr: str = Field(max_length=256)


class SmsSendIn(BaseModel):
    phone: str = Field(max_length=32)
    purpose: str = Field(max_length=16)
    captcha: Captcha | None = None


class SmsLoginIn(BaseModel):
    phone: str = Field(max_length=32)
    code: str = Field(max_length=16)
    agree_terms_version: str | None = Field(default=None, max_length=32)


class RegisterIn(BaseModel):
    handle: str = Field(max_length=64)
    password: str = Field(max_length=512)
    phone: str = Field(max_length=32)
    code: str = Field(max_length=16)
    agree_terms_version: str | None = Field(default=None, max_length=32)


class PasswordLoginIn(BaseModel):
    login: str = Field(max_length=64)
    password: str = Field(max_length=512)


class PasswordResetIn(BaseModel):
    phone: str = Field(max_length=32)
    code: str = Field(max_length=16)
    new_password: str = Field(max_length=512)


class RefreshIn(BaseModel):
    refresh_token: str | None = Field(default=None, max_length=512)


class DeviceCodeIn(BaseModel):
    client_name: str = Field(default="", max_length=120)


class DeviceTokenIn(BaseModel):
    device_code: str = Field(max_length=512)


class DeviceApproveIn(BaseModel):
    user_code: str = Field(max_length=32)


# ---------------- 回包 ----------------


def _cookie_max_age(pair: TokenPair) -> int:
    return max(0, int((pair.session.expires_at - utcnow()).total_seconds()))


def set_refresh_cookie(response: Response, ctx: Context, pair: TokenPair) -> None:
    response.set_cookie(
        ctx.settings.refresh_cookie_name,
        pair.refresh_token,
        max_age=_cookie_max_age(pair),
        path=ctx.settings.refresh_cookie_path,
        httponly=True,
        secure=ctx.settings.cookie_secure,
        samesite="lax",
    )


def clear_refresh_cookie(response: Response, ctx: Context) -> None:
    response.delete_cookie(
        ctx.settings.refresh_cookie_name,
        path=ctx.settings.refresh_cookie_path,
        httponly=True,
        secure=ctx.settings.cookie_secure,
        samesite="lax",
    )


def login_response(ctx: Context, db, pair: TokenPair, *, web: bool, status: int = 200) -> JSONResponse:
    body = {"access_token": pair.access_token, "expires_in": pair.expires_in, "user": me_user(ctx, db, pair.user)}
    if not web:
        body["refresh_token"] = pair.refresh_token
    response = JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})
    if web:
        set_refresh_cookie(response, ctx, pair)
    return response


def _check_terms(ctx: Context, agreed: str | None) -> None:
    if not agreed:
        raise ApiError(400, "terms_required")
    if agreed != ctx.settings.terms_version:
        raise ApiError(400, "terms_outdated")


def _record_terms(user: User, version: str) -> None:
    user.terms_version = version
    user.terms_agreed_at = utcnow()


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:300]


def _auto_handle(db) -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    for _ in range(20):
        handle = "u_" + "".join(secrets.choice(alphabet) for _ in range(8))
        if db.scalar(select(func.count()).select_from(User).where(User.handle == handle)) == 0:
            return handle
    raise ApiError(500, "internal_error")


def _hit(db, key: str, limit: int, window_seconds: int) -> None:
    """一个简单的窗口计数(存库)。超了就 429。调用方负责 commit。"""
    now = utcnow()
    counter = db.get(RateCounter, key)
    if counter is None:
        counter = RateCounter(key=key, window_start=now, count=0)
        db.add(counter)
    elif counter.window_start + timedelta(seconds=window_seconds) < now:
        counter.window_start, counter.count = now, 0
    counter.count += 1
    if counter.count > limit:
        raise ApiError(429, "rate_limited")


# ---------------- 配置 ----------------


@router.get("/config")
def auth_config(ctx: Ctx) -> dict:
    """登录页要知道的公开配置:当前协议版本、人机验证开没开(开了给 CaptchaAppId,它本来就是公开的)。"""
    settings = ctx.settings
    return {
        "terms_version": settings.terms_version,
        "captcha": {"provider": "tencent", "app_id": settings.captcha_app_id} if settings.captcha_enabled else None,
        "sms_code_ttl_seconds": settings.sms_code_ttl_seconds,
        "sms_resend_seconds": settings.sms_resend_seconds,
    }


# ---------------- 短信 ----------------


@router.post("/sms/send", status_code=204)
def sms_send(body: SmsSendIn, request: Request, ctx: Ctx, db: Db) -> Response:
    if body.purpose not in PURPOSES:
        raise ApiError(422, "invalid_purpose")
    phone = normalize_phone(body.phone)
    ip = client_ip(request)
    if ctx.captcha is not None:
        if body.captcha is None:
            raise ApiError(400, "captcha_required")
        if not ctx.captcha.verify(ticket=body.captcha.ticket, randstr=body.captcha.randstr, ip=ip):
            raise ApiError(403, "captcha_failed")
    registered = db.scalar(select(func.count()).select_from(User).where(User.phone == phone)) > 0
    if body.purpose == "bind" and registered:
        raise ApiError(409, "phone_taken")
    if body.purpose == "reset" and not registered:
        # 不告诉对方「这个号码没注册」:找回页不该成为查号器。什么都不发,照样回 204。
        return Response(status_code=204)
    send_code(db, ctx.settings, ctx.sms, phone=phone, purpose=body.purpose, ip=ip)
    return Response(status_code=204)


@router.post("/sms/login")
def sms_login(body: SmsLoginIn, request: Request, ctx: Ctx, db: Db) -> JSONResponse:
    """手机号 + 验证码。第一次用这个号码登录即注册。"""
    _check_terms(ctx, body.agree_terms_version)
    phone = normalize_phone(body.phone)
    verify_code(db, ctx.settings, phone=phone, purpose="login", code=body.code)
    user = db.scalars(select(User).where(User.phone == phone)).first()
    created = user is None
    if user is None:
        handle = _auto_handle(db)
        user = User(handle=handle, display_name=handle, phone=phone)
        db.add(user)
        db.flush()
    elif user.status != STATUS_ACTIVE:
        db.commit()
        raise ApiError(403, "banned")
    _record_terms(user, body.agree_terms_version or "")
    pair = start_session(db, ctx.settings, ctx.keys, user, kind=SESSION_WEB, ip=client_ip(request), user_agent=_user_agent(request))
    db.commit()
    return login_response(ctx, db, pair, web=True, status=201 if created else 200)


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, ctx: Ctx, db: Db) -> JSONResponse:
    """用户名 + 密码注册,必须绑定一个验证过的手机号(用途 `bind`)。"""
    _check_terms(ctx, body.agree_terms_version)
    handle = normalize_handle(body.handle)
    phone = normalize_phone(body.phone)
    check_password_shape(body.password)
    if db.scalar(select(func.count()).select_from(User).where(User.handle == handle)):
        raise ApiError(409, "handle_taken")
    if db.scalar(select(func.count()).select_from(User).where(User.phone == phone)):
        raise ApiError(409, "phone_taken")
    verify_code(db, ctx.settings, phone=phone, purpose="bind", code=body.code)
    user = User(handle=handle, display_name=handle, phone=phone, password_hash=hash_password(body.password))
    _record_terms(user, body.agree_terms_version or "")
    db.add(user)
    db.flush()
    pair = start_session(db, ctx.settings, ctx.keys, user, kind=SESSION_WEB, ip=client_ip(request), user_agent=_user_agent(request))
    db.commit()
    return login_response(ctx, db, pair, web=True, status=201)


_PHONE_LIKE = re.compile(r"^\+?[\d\s-]{7,20}$")


@router.post("/password/login")
def password_login(body: PasswordLoginIn, request: Request, ctx: Ctx, db: Db) -> JSONResponse:
    """用户名或手机号 + 密码。失败按账号、按 IP 两个维度限速。"""
    ip = client_ip(request)
    login = body.login.strip()
    user: User | None = None
    if _PHONE_LIKE.match(login):
        try:
            user = db.scalars(select(User).where(User.phone == normalize_phone(login))).first()
        except ApiError:
            user = None
    else:
        user = db.scalars(select(User).where(User.handle == login.lower())).first()
    account_key = user.id if user is not None else f"unknown:{login.lower()[:64]}"
    check_login_allowed(db, ctx.settings, account_key=account_key, ip=ip)
    if user is None or not verify_password(user.password_hash, body.password):
        record_login_failure(db, ctx.settings, account_key=account_key, ip=ip)
        db.commit()
        log_event(logger, "password login failed", logging.INFO, user_id=user.id if user else None)
        raise ApiError(401, "invalid_credentials")
    if user.status != STATUS_ACTIVE:
        raise ApiError(403, "banned")
    record_login_success(db, account_key=account_key)
    if user.password_hash and needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    pair = start_session(db, ctx.settings, ctx.keys, user, kind=SESSION_WEB, ip=ip, user_agent=_user_agent(request))
    db.commit()
    return login_response(ctx, db, pair, web=True)


@router.post("/password/reset", status_code=204)
def password_reset(body: PasswordResetIn, ctx: Ctx, db: Db) -> Response:
    """手机验证码 → 设新密码 → 吊销这个人的全部会话。"""
    phone = normalize_phone(body.phone)
    check_password_shape(body.new_password)
    verify_code(db, ctx.settings, phone=phone, purpose="reset", code=body.code)
    user = db.scalars(select(User).where(User.phone == phone)).first()
    if user is None:
        raise ApiError(400, "code_invalid")
    user.password_hash = hash_password(body.new_password)
    revoke_all(db, user.id, "password_reset")
    record_login_success(db, account_key=user.id)
    db.commit()
    return Response(status_code=204)


# ---------------- 刷新与退出 ----------------


def _requested_with(request: Request) -> None:
    """用 cookie 刷新时要求 `X-Requested-With`:跨站的表单提交和 <img> 带不上自定义头,配合 SameSite=Lax 防 CSRF。"""
    if not request.headers.get("x-requested-with"):
        raise ApiError(403, "csrf_header_missing")


@router.post("/refresh")
def refresh(request: Request, ctx: Ctx, db: Db, body: Annotated[RefreshIn | None, Body()] = None) -> JSONResponse:
    """网页:刷新令牌在 cookie 里(要 X-Requested-With);应用:`{refresh_token}` 在 body 里。"""
    app_token = body.refresh_token if body is not None else None
    web = not app_token
    if web:
        _requested_with(request)
    raw = app_token or request.cookies.get(ctx.settings.refresh_cookie_name, "")
    try:
        pair = rotate(db, ctx.settings, ctx.keys, raw, ip=client_ip(request), user_agent=_user_agent(request))
    except ApiError as exc:
        db.rollback()
        response = JSONResponse(exc.payload(), status_code=exc.status, headers={"Cache-Control": "no-store"})
        if web:
            clear_refresh_cookie(response, ctx)
        return response
    db.commit()
    return login_response(ctx, db, pair, web=web)


@router.post("/logout", status_code=204)
def logout(request: Request, ctx: Ctx, db: Db, body: Annotated[RefreshIn | None, Body()] = None) -> Response:
    """吊销当前会话:认访问令牌里的会话;没有访问令牌时认刷新令牌(body 里的,或 cookie 里的)。"""
    session: AuthSession | None = None
    try:
        principal = resolve_principal(request, db)
    except ApiError:
        principal = None
    if principal is not None:
        session = db.get(AuthSession, principal.session_id)
    elif body is not None and body.refresh_token:
        session = session_for_refresh(db, body.refresh_token)
    elif request.cookies.get(ctx.settings.refresh_cookie_name):
        _requested_with(request)
        session = session_for_refresh(db, request.cookies[ctx.settings.refresh_cookie_name])
    if session is not None:
        revoke_session(db, session, "logout")
        db.commit()
    response = Response(status_code=204)
    clear_refresh_cookie(response, ctx)
    return response


# ---------------- 设备授权(RFC 8628) ----------------


def _user_code() -> str:
    raw = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_user_code(raw: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", raw or "").upper()
    return f"{letters[:4]}-{letters[4:]}" if len(letters) == 8 else ""


@router.post("/device/code")
def device_code(body: DeviceCodeIn, request: Request, ctx: Ctx, db: Db) -> JSONResponse:
    ip = client_ip(request)
    _hit(db, f"device:ip:{ip}", DEVICE_CODES_PER_IP_PER_HOUR, 3600)
    device = random_token(32)
    for _ in range(10):
        code = _user_code()
        if db.scalar(select(func.count()).select_from(DeviceAuthorization).where(DeviceAuthorization.user_code == code)) == 0:
            break
    else:  # pragma: no cover - 20^8 个码撞十次
        raise ApiError(500, "internal_error")
    now = utcnow()
    db.add(
        DeviceAuthorization(
            device_code_hash=sha256_hex(device),
            user_code=code,
            client_name=body.client_name.strip()[:120],
            ip=ip[:64],
            interval=DEVICE_POLL_INTERVAL,
            created_at=now,
            expires_at=now + timedelta(seconds=DEVICE_CODE_TTL_SECONDS),
        )
    )
    db.commit()
    verification_uri = f"{ctx.settings.public_url}/{current_locale()}/device"
    return JSONResponse(
        {
            "device_code": device,
            "user_code": code,
            "verification_uri": verification_uri,
            "verification_uri_complete": f"{verification_uri}?code={code}",
            "expires_in": DEVICE_CODE_TTL_SECONDS,
            "interval": DEVICE_POLL_INTERVAL,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/device/token")
def device_token(body: DeviceTokenIn, request: Request, ctx: Ctx, db: Db) -> JSONResponse:
    """轮询。未确认 428 `authorization_pending`、太快 429 `slow_down`(间隔加 5 秒)、过期 410、成功给令牌对。"""
    grant = db.scalars(
        select(DeviceAuthorization).where(DeviceAuthorization.device_code_hash == sha256_hex(body.device_code)).with_for_update()
    ).first()
    if grant is None or grant.status == "consumed":
        raise ApiError(400, "device_code_invalid")
    now = utcnow()
    if grant.expires_at <= now:
        raise ApiError(410, "expired_token")
    if grant.status == "denied":
        raise ApiError(403, "access_denied")
    if grant.last_polled_at is not None and (now - grant.last_polled_at).total_seconds() < grant.interval:
        grant.interval += 5
        grant.last_polled_at = now
        db.commit()
        raise ApiError(429, "slow_down", headers={"Retry-After": str(grant.interval)})
    grant.last_polled_at = now
    if grant.status != "approved" or grant.user_id is None:
        db.commit()
        raise ApiError(428, "authorization_pending")
    user = db.get(User, grant.user_id)
    if user is None or user.status != STATUS_ACTIVE:
        grant.status = "denied"
        db.commit()
        raise ApiError(403, "access_denied")
    grant.status = "consumed"
    pair = start_session(
        db,
        ctx.settings,
        ctx.keys,
        user,
        kind=SESSION_APP,
        device_name=grant.client_name or "Mosael",
        ip=client_ip(request),
        user_agent=_user_agent(request),
    )
    db.commit()
    return login_response(ctx, db, pair, web=False)


@router.post("/device/approve", status_code=204)
def device_approve(body: DeviceApproveIn, principal: CurrentUser, db: Db) -> Response:
    """登录后的用户在网页上确认「允许这台 Mosael 访问你的社区账号」。"""
    code = normalize_user_code(body.user_code)
    grant = db.scalars(select(DeviceAuthorization).where(DeviceAuthorization.user_code == code)).first() if code else None
    if grant is None or grant.status == "consumed":
        raise ApiError(404, "user_code_invalid")
    if grant.expires_at <= utcnow():
        raise ApiError(410, "expired_token")
    if grant.status == "approved":
        if grant.user_id == principal.user.id:
            return Response(status_code=204)
        raise ApiError(409, "user_code_used")
    grant.status = "approved"
    grant.user_id = principal.user.id
    grant.approved_at = utcnow()
    db.commit()
    log_event(logger, "device approved", user_id=principal.user.id, client=grant.client_name)
    return Response(status_code=204)


__all__ = ["clear_refresh_cookie", "login_response", "normalize_user_code", "router", "set_refresh_cookie"]
