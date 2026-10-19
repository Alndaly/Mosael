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
from cloud.config import CloudConfig
from cloud.errors import CloudError
from cloud.models import CloudSession, CloudUser, now
from cloud.security import hash_password, new_token, token_digest, verify_password

router = APIRouter(tags=["accounts"])


class SignupIn(BaseModel):
    email: EmailStr
    #: 长度策略在路由里判 —— 报错要能说清"至少几位",而不是 pydantic 的字段路径。
    password: str = Field(min_length=1, max_length=512)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


def user_out(user: CloudUser) -> dict[str, object]:
    """交给界面的账号样子。**密码哈希永远不出现在任何响应里。**"""
    return {
        "id": user.id,
        "email": user.email,
        "email_verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None,
        "created_at": user.created_at.isoformat(),
    }


def set_session_cookie(response: Response, config: CloudConfig, raw: str, max_age: int) -> None:
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


@router.post("/signup", status_code=201)
def signup(body: SignupIn, db: DbSession, config: CurrentConfig) -> dict[str, object]:
    """注册**不自动登录**:官网把用户送到登录页,让"注册"和"登录"各自只有一件事。"""
    if len(body.password) < config.password_min_length:
        raise CloudError(400, "password_too_short", min=config.password_min_length)
    if len(body.password) > config.password_max_length:
        raise CloudError(400, "password_too_long", max=config.password_max_length)

    email = str(body.email).strip().lower()
    if db.scalar(select(CloudUser.id).where(CloudUser.email == email)) is not None:
        raise CloudError(409, "email_taken")

    user = CloudUser(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # 并发注册同一个邮箱:唯一索引先撞上,给同一句人话。
        db.rollback()
        raise CloudError(409, "email_taken") from exc
    return {"user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, db: DbSession, config: CurrentConfig, response: Response) -> dict[str, object]:
    email = str(body.email).strip().lower()
    user = db.scalar(select(CloudUser).where(CloudUser.email == email))
    # 不区分"邮箱没注册"和"密码错" —— 否则这个接口就成了账号探测器。
    if user is None or not verify_password(body.password, user.password_hash):
        raise CloudError(401, "invalid_credentials")

    raw = new_token()
    expires_at = now() + timedelta(days=config.session_ttl_days)
    db.add(CloudSession(token_hash=token_digest(raw), user_id=user.id, expires_at=expires_at))
    db.commit()

    set_session_cookie(response, config, raw, max_age=int((expires_at - now()).total_seconds()))
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_out(user)}


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
    return {"user": user_out(user)}


@router.delete("/me", status_code=204)
def delete_me(user: CurrentUser, db: DbSession, config: CurrentConfig):
    db.delete(user)
    db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, config)
    return response
