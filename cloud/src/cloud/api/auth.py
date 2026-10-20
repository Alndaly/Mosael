"""账号:注册、登录、登出、/me、删号。

**会话是一个 HttpOnly cookie,不是返回给 JS 的令牌。** 这是刻意的:官网这一期是纯浏览器页面,
令牌放进 localStorage 等于把长期凭据交给任何一段注入脚本。cookie 带 HttpOnly + SameSite=Lax,
写请求另过 `app.py` 的同源校验。
"""

from __future__ import annotations

from datetime import timedelta
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cloud.api.deps import CurrentConfig, CurrentUser, DbSession
from cloud.config import API_PREFIX, CloudConfig
from cloud.domain.identity import account_user
from cloud.email_codes import consume_code, issue_code
from cloud.errors import CloudError
from cloud.models import CloudSession, CloudUser, now
from cloud.security import hash_password, new_token, token_digest, verify_password

router = APIRouter(tags=["accounts"])


class EmailIn(BaseModel):
    email: EmailStr


class SignupIn(BaseModel):
    email: EmailStr
    #: 先 POST /signup/code 拿到的 6 位码。留空由路由给一句"请输入验证码",而不是 pydantic 的字段路径。
    code: str = Field(default="", max_length=12)
    #: 长度策略在路由里判 —— 报错要能说清"至少几位",而不是 pydantic 的字段路径。
    password: str = Field(min_length=1, max_length=512)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class LoginCodeIn(BaseModel):
    email: EmailStr
    code: str = Field(default="", max_length=12)


def request_ip(request: Request) -> str:
    """限流用的来源 IP。反代后面要开 uvicorn 的 proxy headers,否则这里看到的是代理地址。"""
    return request.client.host if request.client is not None else ""


def set_session_cookie(response: Response, config: CloudConfig, raw: str, max_age: int) -> None:
    # 一次性清理:早先的会话 cookie 被限定在 `/api/cloud/v1` 上,浏览器里可能还留着一条同名的。
    # 同名不同 path 的两条会一起发给接口,服务端收到哪条全看解析顺序 —— 那会让"登录了却像没登录"
    # 随机复现。发新 cookie 的同时把旧路径那条作废,不留两套。
    response.delete_cookie(config.cookie_name, path=API_PREFIX, httponly=True,
                           secure=config.cookie_secure, samesite="lax")
    response.set_cookie(
        config.cookie_name,
        raw,
        max_age=max_age,
        path=config.cookie_path,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
    )


def clear_session_cookie(response: Response, config: CloudConfig) -> None:
    response.delete_cookie(
        config.cookie_name,
        path=config.cookie_path,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
    )


def open_session(db, config: CloudConfig, user: CloudUser, response: Response) -> None:
    """给一次成功的认证发会话。注册、密码登录、验证码登录、第三方登录**共用这一条路径**,行为才不会分叉。"""
    raw = new_token()
    expires_at = now() + timedelta(days=config.session_ttl_days)
    db.add(CloudSession(token_hash=token_digest(raw), user_id=user.id, expires_at=expires_at))
    db.commit()

    set_session_cookie(response, config, raw, max_age=int((expires_at - now()).total_seconds()))
    response.headers["Cache-Control"] = "no-store"


@router.post("/signup/code")
def signup_code(body: EmailIn, db: DbSession, request: Request) -> dict[str, object]:
    """注册第一步:把 6 位码发到这个邮箱。已注册的邮箱直接 409(注册页本来就会说)。"""
    email = str(body.email).strip().lower()
    issue_code(
        db,
        email=email,
        purpose="signup",
        request_ip=request_ip(request),
        sender=request.app.state.code_sender,
    )
    return {"sent": True}


@router.post("/signup", status_code=201)
def signup(body: SignupIn, db: DbSession, config: CurrentConfig, response: Response) -> dict[str, object]:
    """注册:**必须带邮箱验证码**,验过才建账号,并把 `email_verified_at` 写上。

    **注册成功即登录**:和密码 / 验证码登录共用同一个 `open_session`,响应里直接是会话
    cookie,紧接着 `GET /me` 就是 200。注册页不必再让用户"用刚设的邮箱登录一次"。
    """
    if len(body.password) < config.password_min_length:
        raise CloudError(400, "password_too_short", min=config.password_min_length)
    if len(body.password) > config.password_max_length:
        raise CloudError(400, "password_too_long", max=config.password_max_length)

    email = str(body.email).strip().lower()
    # 先看重复:已注册的邮箱没有可发的注册码,直接给 409,别让人先等一封邮件。
    if db.scalar(select(CloudUser.id).where(CloudUser.email == email)) is not None:
        raise CloudError(409, "email_taken")

    code = body.code.strip()
    if not code:
        raise CloudError(400, "email_code_required")
    consume_code(db, email=email, purpose="signup", code=code)

    user = CloudUser(email=email, password_hash=hash_password(body.password), email_verified_at=now())
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # 并发注册同一个邮箱:唯一索引先撞上,给同一句人话。
        db.rollback()
        raise CloudError(409, "email_taken") from exc
    open_session(db, config, user, response)
    return {"user": account_user(user)}


@router.post("/login")
def login(body: LoginIn, db: DbSession, config: CurrentConfig, response: Response) -> dict[str, object]:
    email = str(body.email).strip().lower()
    user = db.scalar(select(CloudUser).where(CloudUser.email == email))
    # 不区分"邮箱没注册"和"密码错" —— 否则这个接口就成了账号探测器。
    # 第三方登录建出来的账号 `password_hash` 为空:它没有密码可验,只能走验证码那条路。
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise CloudError(401, "invalid_credentials")

    open_session(db, config, user, response)
    return {"user": account_user(user)}


@router.post("/login/code")
def send_login_code(body: EmailIn, db: DbSession, request: Request) -> dict[str, object]:
    """登录第一步:发码。**未注册邮箱也回同一句** `{"sent": true}`,不泄露这个邮箱有没有注册。"""
    email = str(body.email).strip().lower()
    issue_code(
        db,
        email=email,
        purpose="login",
        request_ip=request_ip(request),
        sender=request.app.state.code_sender,
    )
    return {"sent": True}


@router.post("/login/code/verify")
def login_with_code(
    body: LoginCodeIn, db: DbSession, config: CurrentConfig, response: Response
) -> dict[str, object]:
    """登录第二步:码换会话。会话 cookie 与密码登录完全同一条路径。"""
    email = str(body.email).strip().lower()
    code = body.code.strip()
    if not code:
        raise CloudError(400, "email_code_required")

    user = db.scalar(select(CloudUser).where(CloudUser.email == email))
    if user is None:
        # 未知邮箱根本收不到码;统一报"码无效",与"码错"不可区分。
        raise CloudError(400, "email_code_invalid")
    consume_code(db, email=email, purpose="login", code=code)

    open_session(db, config, user, response)
    return {"user": account_user(user)}


@router.post("/logout", status_code=204)
def logout(request: Request, db: DbSession, config: CurrentConfig):
    """只撤这一份会话,别的设备 / 浏览器照旧登录着。"""
    raw = request.cookies.get(config.cookie_name, "")
    if not raw:
        raise CloudError(401, "not_authenticated")
    session = db.get(CloudSession, token_digest(raw))
    if session is not None:
        db.delete(session)
        db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, config)
    return response


@router.get("/me")
def me(user: CurrentUser) -> dict[str, object]:
    return {"user": account_user(user)}


@router.delete("/me", status_code=204)
def delete_me(user: CurrentUser, db: DbSession, config: CurrentConfig):
    db.delete(user)
    db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, config)
    return response
