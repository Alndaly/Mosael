"""第三方登录(Google / Apple)— 桌面友好的授权码流。

形态:前端 `start` 拿到授权 URL(系统浏览器打开)+ 一次性 pending_id;
提供方回调打到本机后端(回环地址),后端换码、解出身份、找到/创建本地账号、
铸造会话 token 存进 pending 槽;前端轮询 `pending/{id}` 取票完成登录。
这样 file://(Electron)与 5173(网页开发)都不需要把自己注册成重定向目标。

id_token 直接解 payload 不验签:它来自我们主动发起的、对提供方 token 端点的
TLS 请求响应体,不经过用户手,验签在这个信道里是冗余防御;换任何一步走
用户可控输入(如 implicit flow)则必须验签。

Google:标准 authorization-code + PKCE(S256),回环 HTTP 回调可直接登记。
Apple:同为 code 流,但 Apple 要求 HTTPS 回调且 scope 带 name/email 时用
form_post —— 适用于有公网域名的团队部署;client_secret 是按 Apple 规范用
团队密钥签好的 JWT,整串填进配置即可。
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import hash_password, new_session_token
from app.db.models import AuthSession, OAuthIdentity, User

router = APIRouter(tags=["oauth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"

_PENDING_TTL_S = 600.0
_pending_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}  # pending_id → {provider, state, verifier, created, token?, error?}


def _providers() -> list[str]:
    configured = []
    if settings.google_client_id and settings.google_client_secret:
        configured.append("google")
    if settings.apple_client_id and settings.apple_client_secret:
        configured.append("apple")
    return configured


def _redirect_uri(provider: str) -> str:
    base = settings.oauth_redirect_base or f"http://{settings.backend_host}:{settings.backend_port}"
    return f"{base}/api/auth/oauth/{provider}/callback"


def _prune_pending() -> None:
    horizon = time.time() - _PENDING_TTL_S
    for key in [k for k, v in _pending.items() if v["created"] < horizon]:
        _pending.pop(key, None)


class StartOut(BaseModel):
    pending_id: str
    url: str


@router.get("/auth/oauth/providers")
def list_providers() -> dict[str, Any]:
    return {"providers": _providers()}


@router.post("/auth/oauth/{provider}/start", response_model=StartOut)
def start(provider: str) -> StartOut:
    if provider not in _providers():
        raise HTTPException(status_code=404, detail="该登录方式未配置")
    pending_id = secrets.token_urlsafe(24)
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    with _pending_lock:
        _prune_pending()
        _pending[pending_id] = {"provider": provider, "state": state, "verifier": verifier, "created": time.time()}

    if provider == "google":
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": _redirect_uri("google"),
            "response_type": "code",
            "scope": "openid email profile",
            "state": f"{pending_id}.{state}",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"{GOOGLE_AUTH_URL}?{httpx.QueryParams(params)}"
    else:  # apple
        params = {
            "client_id": settings.apple_client_id,
            "redirect_uri": _redirect_uri("apple"),
            "response_type": "code",
            "scope": "name email",
            "response_mode": "form_post",
            "state": f"{pending_id}.{state}",
        }
        url = f"{APPLE_AUTH_URL}?{httpx.QueryParams(params)}"
    return StartOut(pending_id=pending_id, url=url)


@router.get("/auth/oauth/pending/{pending_id}")
def poll_pending(pending_id: str) -> dict[str, Any]:
    with _pending_lock:
        _prune_pending()
        entry = _pending.get(pending_id)
        if entry is None:
            return {"status": "expired"}
        if entry.get("error"):
            _pending.pop(pending_id, None)
            return {"status": "error", "error": entry["error"]}
        if entry.get("token"):
            _pending.pop(pending_id, None)  # 一次性取票
            return {"status": "done", "token": entry["token"], "user": entry["user"]}
    return {"status": "waiting"}


@router.get("/auth/oauth/{provider}/callback")
def callback_get(provider: str, request: Request, db: DbSession) -> HTMLResponse:
    return _handle_callback(provider, dict(request.query_params), db)


@router.post("/auth/oauth/{provider}/callback")
async def callback_post(provider: str, request: Request, db: DbSession) -> HTMLResponse:
    form = await request.form()  # Apple 的 form_post 回调
    return _handle_callback(provider, {k: str(v) for k, v in form.items()}, db)


def _handle_callback(provider: str, params: dict[str, str], db: Session) -> HTMLResponse:
    state_raw = params.get("state") or ""
    pending_id, _, state = state_raw.partition(".")
    with _pending_lock:
        entry = _pending.get(pending_id)
    if entry is None or entry["provider"] != provider or not secrets.compare_digest(entry["state"], state):
        return _result_page("登录请求已过期或不匹配,请回到 Mibu 重试。", ok=False)
    if params.get("error"):
        _finish(pending_id, error=f"授权被拒绝:{params['error']}")
        return _result_page("授权被拒绝,可以关闭本页。", ok=False)
    code = params.get("code") or ""
    if not code:
        _finish(pending_id, error="提供方未返回授权码")
        return _result_page("提供方未返回授权码,请回到 Mibu 重试。", ok=False)
    try:
        claims = _exchange_code(provider, code, entry["verifier"])
        user = _find_or_create_user(
            db,
            provider=provider,
            subject=str(claims.get("sub") or ""),
            email=str(claims.get("email") or ""),
            display_name=str(claims.get("name") or ""),
        )
        token = new_session_token()
        db.add(AuthSession(token=token, user_id=user.id))
        db.commit()
        _finish(pending_id, token=token, user={"id": user.id, "username": user.username, "display_name": user.display_name})
    except Exception as exc:  # 把原因带回前端轮询,而不是让用户对着浏览器空页猜
        _finish(pending_id, error=str(exc)[:300])
        return _result_page("登录失败,请回到 Mibu 查看原因。", ok=False)
    return _result_page("登录成功,回到 Mibu 即可,本页可以关闭。", ok=True)


def _finish(pending_id: str, *, token: str | None = None, user: dict | None = None, error: str | None = None) -> None:
    with _pending_lock:
        entry = _pending.get(pending_id)
        if entry is None:
            return
        if error:
            entry["error"] = error
        else:
            entry["token"] = token
            entry["user"] = user


def _exchange_code(provider: str, code: str, verifier: str) -> dict[str, Any]:
    if provider == "google":
        body = {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri("google"),
        }
        token_url = GOOGLE_TOKEN_URL
    else:
        body = {
            "client_id": settings.apple_client_id,
            "client_secret": settings.apple_client_secret,  # Apple 规范签好的 JWT
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri("apple"),
        }
        token_url = APPLE_TOKEN_URL
    response = httpx.post(token_url, data=body, timeout=15.0)
    data = response.json() if response.content else {}
    if response.status_code != 200 or "id_token" not in data:
        raise RuntimeError(f"换取令牌失败:{data.get('error_description') or data.get('error') or response.status_code}")
    return _decode_jwt_payload(str(data["id_token"]))


def _decode_jwt_payload(id_token: str) -> dict[str, Any]:
    try:
        payload = id_token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:
        raise RuntimeError("id_token 无法解析") from exc


def _find_or_create_user(db: Session, *, provider: str, subject: str, email: str, display_name: str) -> User:
    if not subject:
        raise RuntimeError("提供方未返回用户标识(sub)")
    identity = db.get(OAuthIdentity, {"provider": provider, "subject": subject})
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is not None:
            return user
        db.delete(identity)  # 悬空身份(账号已删)→ 当作首次登录重建
        db.flush()
    base = (email.split("@")[0] if email else f"{provider}用户").strip().lower() or provider
    username = base
    suffix = 1
    while db.scalar(select(User).where(User.username == username)) is not None:
        suffix += 1
        username = f"{base}{suffix}"
    # 第三方账号没有本地口令:填一个不可用的随机散列,密码登录路径天然走不通。
    user = User(
        username=username,
        display_name=(display_name or base).strip() or username,
        signature="",
        password_hash=hash_password(secrets.token_hex(24)),
    )
    db.add(user)
    db.flush()
    db.add(OAuthIdentity(provider=provider, subject=subject, user_id=user.id, email=email))
    return user


def _result_page(message: str, *, ok: bool) -> HTMLResponse:
    tone = "#2f9e8f" if ok else "#c0554d"
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Mibu</title>"
        "<body style=\"display:grid;place-items:center;min-height:96vh;margin:0;"
        "font-family:system-ui,-apple-system,'PingFang SC',sans-serif;background:#f6f4f0;color:#3d3a45\">"
        f"<div style='text-align:center'><div style='font-size:34px;color:{tone}'>{'✓' if ok else '✕'}</div>"
        f"<p style='font-size:15px'>{message}</p></div></body>"
    )
