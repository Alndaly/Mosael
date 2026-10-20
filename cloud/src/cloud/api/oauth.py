"""第三方登录的 HTTP 入口:`/oauth/{provider}/start` 与 `/oauth/{provider}/callback`。

浏览器侧只有两条同源 GET:

    /oauth/providers                 哪些入口已配置(官网据此决定渲不渲染按钮)
    /oauth/{provider}/start?locale=…&from=login|signup
                                     生成 state / nonce / PKCE,302 到第三方
    /oauth/{provider}/callback?code=…&state=…
                                     校验一次性 state + 浏览器绑定,换 token、取身份、
                                     走**现有的** open_session 发会话,302 回官网

失败也 302 回官网,带 `oauth_error=<稳定错误码>`;中英文案由官网按当前语言挑(和后端 JSON
里的 `{error, message:{en,zh}}` 是同一组错误码)。**provider 的原始报错只进日志。**
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from cloud.api.auth import open_session
from cloud.api.deps import CurrentConfig, DbSession
from cloud.config import OAUTH_PROVIDERS, CloudConfig
from cloud.errors import CloudError
from cloud.models import CloudIdentity, CloudOAuthState, CloudSession, CloudUser, now
from cloud.oauth import (
    OAuthProvider,
    OAuthProviderError,
    code_challenge,
    new_code_verifier,
)
from cloud.security import new_token, token_digest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["oauth"])

LOCALES = frozenset({"en", "zh"})
RETURN_PAGES = frozenset({"login", "signup"})
PROVIDER_LABELS = {"github": "GitHub", "google": "Google"}

#: 这些第三方错误码说明"授权码或 PKCE 没通过",其余(网络、5xx、配置错)归为 provider error。
CODE_REJECTED_ERRORS = frozenset({"invalid_grant", "bad_verification_code"})


def _locale(value: str | None) -> str:
    return value if value in LOCALES else "en"


def _page(value: str | None) -> str:
    return value if value in RETURN_PAGES else "login"


def _failure_url(config: CloudConfig, locale: str, page: str, code: str) -> str:
    return f"{config.public_url}/{locale}/{page}?{urlencode({'oauth_error': code})}"


def _success_url(config: CloudConfig, locale: str, outcome: str) -> str:
    return f"{config.public_url}/{locale}/account?{urlencode({'oauth': outcome})}"


def _set_nonce_cookie(response: RedirectResponse, config: CloudConfig, nonce: str) -> None:
    response.set_cookie(
        config.oauth_cookie_name,
        nonce,
        max_age=config.oauth_state_ttl_seconds,
        path=config.cookie_path,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
    )


def _clear_nonce_cookie(response: RedirectResponse, config: CloudConfig) -> None:
    response.delete_cookie(
        config.oauth_cookie_name,
        path=config.cookie_path,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
    )


def _failure(config: CloudConfig, locale: str, page: str, code: str) -> RedirectResponse:
    response = RedirectResponse(_failure_url(config, locale, page, code), status_code=302)
    _clear_nonce_cookie(response, config)
    return response


def _provider(request: Request, config: CloudConfig, name: str) -> OAuthProvider | None:
    """已配置且注入了实现才可用。**未配置返回 None,调用方明确报"没启用"。**"""
    if name not in OAUTH_PROVIDERS or not config.oauth_configured(name):
        return None
    return request.app.state.oauth_providers.get(name)


def _session_user(request: Request, db: DbSession, config: CloudConfig) -> CloudUser | None:
    """可选的当前用户:发起登录时已登录 = 这次是"绑定到当前账号";否则就是登录 / 注册。"""
    raw = request.cookies.get(config.cookie_name, "")
    if not raw:
        return None
    session = db.get(CloudSession, token_digest(raw))
    if session is None or session.expires_at <= now():
        return None
    return db.get(CloudUser, session.user_id)


@router.get("/oauth/providers")
def oauth_providers(config: CurrentConfig) -> dict[str, object]:
    """官网据此决定渲不渲染按钮。**只回答 true/false,不泄露 client id / secret。**"""
    return {"providers": {name: config.oauth_configured(name) for name in OAUTH_PROVIDERS}}


@router.get("/oauth/{provider}/start")
def oauth_start(
    provider: str, request: Request, db: DbSession, config: CurrentConfig
) -> RedirectResponse:
    locale = _locale(request.query_params.get("locale"))
    page = _page(request.query_params.get("from"))
    implementation = _provider(request, config, provider)
    if implementation is None:
        return _failure(config, locale, page, "oauth_not_configured")

    state = new_token()
    nonce = new_token()
    verifier = new_code_verifier()
    user = _session_user(request, db, config)
    db.add(
        CloudOAuthState(
            state_hash=token_digest(state),
            provider=provider,
            code_verifier=verifier,
            nonce_hash=token_digest(nonce),
            link_user_id=user.id if user is not None else None,
            locale=locale,
            return_page=page,
            expires_at=now() + timedelta(seconds=config.oauth_state_ttl_seconds),
        )
    )
    db.commit()

    response = RedirectResponse(
        implementation.authorize_url(
            config=config,
            # 回调地址只由 public_url 推出(见 CloudConfig),必须与官网同源。
            redirect_uri=config.oauth_redirect_uri(provider),
            state=state,
            code_challenge=code_challenge(verifier),
        ),
        status_code=302,
    )
    _set_nonce_cookie(response, config, nonce)
    return response


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    db: DbSession,
    config: CurrentConfig,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    row = (
        db.scalar(select(CloudOAuthState).where(CloudOAuthState.state_hash == token_digest(state)))
        if state
        else None
    )
    locale = row.locale if row is not None else _locale(request.query_params.get("locale"))
    page = row.return_page if row is not None else _page(request.query_params.get("from"))

    implementation = _provider(request, config, provider)
    if implementation is None:
        return _failure(config, locale, page, "oauth_not_configured")
    if row is None or row.provider != provider:
        return _failure(config, locale, page, "oauth_state_invalid")

    # state 必须属于发起它的这个浏览器:nonce cookie 是同一枚 state 的绑定。
    cookie = request.cookies.get(config.oauth_cookie_name, "")
    if not cookie or not secrets.compare_digest(token_digest(cookie), row.nonce_hash):
        return _failure(config, locale, page, "oauth_state_invalid")
    if row.used_at is not None or row.expires_at <= now():
        return _failure(config, locale, page, "oauth_state_invalid")

    # 先原子地消费,再换 token:两个并发的回调只有一个能拿到 code_verifier。
    consumed = db.execute(
        update(CloudOAuthState)
        .where(CloudOAuthState.state_hash == row.state_hash, CloudOAuthState.used_at.is_(None))
        .values(used_at=now())
    )
    if consumed.rowcount != 1:
        db.rollback()
        return _failure(config, locale, page, "oauth_state_invalid")
    db.commit()

    if error:
        # 最常见的是 access_denied:用户在第三方点了"取消"。原因记日志,响应只给稳定错误码。
        logger.info("oauth %s authorization denied by the provider (%s)", provider, error)
        return _failure(config, locale, page, "oauth_denied")
    if not code:
        return _failure(config, locale, page, "oauth_callback_invalid")

    try:
        access_token = implementation.exchange_code(
            config=config,
            code=code,
            redirect_uri=config.oauth_redirect_uri(provider),
            code_verifier=row.code_verifier,
        )
    except OAuthProviderError as failure:
        # 原始 error / error_description 只进日志(可能是第三方内部信息)。
        logger.warning(
            "oauth %s token exchange failed (%s: %s)", provider, failure.code, failure.detail
        )
        reason = "oauth_code_rejected" if failure.code in CODE_REJECTED_ERRORS else "oauth_provider_error"
        return _failure(config, locale, page, reason)

    try:
        identity = implementation.fetch_identity(config=config, access_token=access_token)
    except OAuthProviderError as failure:
        logger.warning(
            "oauth %s userinfo failed (%s: %s)", provider, failure.code, failure.detail
        )
        return _failure(config, locale, page, "oauth_provider_error")

    email = (identity.email or "").strip().lower()
    if not identity.email_verified or not email:
        return _failure(config, locale, page, "oauth_email_unverified")
    try:
        # 第三方说"已验证"仍要确认它是个合法邮箱;不合法同样归到"没有可用邮箱"。
        email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return _failure(config, locale, page, "oauth_email_unverified")

    label = PROVIDER_LABELS[provider]
    try:
        user, outcome = _resolve_account(
            db,
            provider=provider,
            provider_user_id=identity.provider_user_id,
            email=email,
            link_user_id=row.link_user_id,
            label=label,
        )
    except CloudError as failure:
        return _failure(config, locale, page, failure.code)

    response = RedirectResponse(_success_url(config, locale, outcome), status_code=302)
    # **复用现有的 open_session** —— 第三方登录没有第二条鉴权路径。
    open_session(db, config, user, response)
    _clear_nonce_cookie(response, config)
    return response


def _resolve_account(
    db,
    *,
    provider: str,
    provider_user_id: str,
    email: str,
    link_user_id: str | None,
    label: str,
) -> tuple[CloudUser, str]:
    """把一次第三方登录落到一个 Cloud 账号上。返回 `(user, "existing"|"created")`。

    三条路:
    1. 已登录(link_user_id)→ 绑到当前账号;这个第三方 id 已属于别人 → 冲突。
    2. 这个第三方 id 已绑过 → 登录它指向的账号(不重复建号)。
    3. 没绑过 → 按**已验证邮箱**找已有账号:有就绑上去,没有就新建一个无密码账号。
    """
    existing = db.scalar(
        select(CloudIdentity).where(
            CloudIdentity.provider == provider,
            CloudIdentity.provider_user_id == provider_user_id,
        )
    )

    if link_user_id is not None:
        if existing is not None and existing.cloud_user_id != link_user_id:
            raise CloudError(409, "oauth_identity_conflict", provider=label)
        user = db.get(CloudUser, link_user_id)
        if user is None:
            raise CloudError(400, "oauth_state_invalid")
        if existing is None:
            db.add(
                CloudIdentity(
                    provider=provider,
                    provider_user_id=provider_user_id,
                    cloud_user_id=user.id,
                )
            )
            try:
                db.commit()
            except IntegrityError as failure:
                db.rollback()
                raise CloudError(409, "oauth_identity_conflict", provider=label) from failure
        return user, "existing"

    if existing is not None:
        owner = db.get(CloudUser, existing.cloud_user_id)
        if owner is None:
            raise CloudError(400, "oauth_state_invalid")
        # 这个第三方 id 已经是某个账号的绑定;如果它现在返回的已验证邮箱属于**另一个**
        # Cloud 账号,就不猜"该登进谁" —— 明确报冲突,让人去处理账号归属。
        email_owner = db.scalar(select(CloudUser).where(CloudUser.email == email))
        if email_owner is not None and email_owner.id != owner.id:
            raise CloudError(409, "oauth_identity_conflict", provider=label)
        return owner, "existing"

    user = db.scalar(select(CloudUser).where(CloudUser.email == email))
    outcome = "existing"
    if user is None:
        user = CloudUser(email=email, password_hash=None, email_verified_at=now())
        db.add(user)
        db.flush()
        outcome = "created"

    db.add(
        CloudIdentity(
            provider=provider,
            provider_user_id=provider_user_id,
            cloud_user_id=user.id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # 并发:另一个请求抢先建了同一个邮箱的账号或同一个第三方身份。回到库里再判一次。
        db.rollback()
        return _resolve_race(
            db, provider=provider, provider_user_id=provider_user_id, email=email, label=label
        )
    return user, outcome


def _resolve_race(
    db, *, provider: str, provider_user_id: str, email: str, label: str
) -> tuple[CloudUser, str]:
    """唯一约束撞车后的恢复:身份已经存在就登录它的所有者;邮箱账号已存在就绑上去。"""
    existing = db.scalar(
        select(CloudIdentity).where(
            CloudIdentity.provider == provider,
            CloudIdentity.provider_user_id == provider_user_id,
        )
    )
    if existing is not None:
        owner = db.get(CloudUser, existing.cloud_user_id)
        if owner is None:
            raise CloudError(400, "oauth_state_invalid")
        # 这个第三方 id 已经是某个账号的绑定;如果它现在返回的已验证邮箱属于**另一个**
        # Cloud 账号,就不猜"该登进谁" —— 明确报冲突,让人去处理账号归属。
        email_owner = db.scalar(select(CloudUser).where(CloudUser.email == email))
        if email_owner is not None and email_owner.id != owner.id:
            raise CloudError(409, "oauth_identity_conflict", provider=label)
        return owner, "existing"

    user = db.scalar(select(CloudUser).where(CloudUser.email == email))
    if user is None:
        raise CloudError(500, "internal_error")

    db.add(
        CloudIdentity(
            provider=provider,
            provider_user_id=provider_user_id,
            cloud_user_id=user.id,
        )
    )
    try:
        db.commit()
    except IntegrityError as failure:
        db.rollback()
        existing = db.scalar(
            select(CloudIdentity).where(
                CloudIdentity.provider == provider,
                CloudIdentity.provider_user_id == provider_user_id,
            )
        )
        if existing is None:
            raise CloudError(500, "internal_error") from failure
        owner = db.get(CloudUser, existing.cloud_user_id)
        if owner is None:
            raise CloudError(400, "oauth_state_invalid") from failure
        return owner, "existing"
    return user, "existing"
