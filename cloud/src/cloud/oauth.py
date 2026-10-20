"""第三方登录的 provider 客户端:OAuth 2.0 **授权码 + PKCE(S256)**。

三条边界写死在这里:

1. **不碰隐式流**。授权码只在服务端之间交换,浏览器地址栏拿不到 access token;
   `state` 由我们生成并只在服务端存哈希,`code_verifier` 只在换 token 那一次使用。
2. **只把"第三方声明已验证的邮箱"当成身份**。GitHub 需要 `/user/emails` 里 `verified: true`,
   Google 需要 userinfo 里 `email_verified: true`;没验证就不认。
3. **测试不真连第三方**。`OAuthProvider` 是协议,`create_app` 注入假实现(和 `CodeSender`
   同一个套路);真机验证也走假 provider,uvicorn 下跑完整 HTTP 链路。

provider 的原始报错只进日志(`logger.warning`),不进响应 —— 响应里只有我们自己写的中英文案。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from cloud.config import CloudConfig

logger = logging.getLogger(__name__)

#: 一次对第三方的请求最多等多久。回调是用户正在等的页面,不能被挂死的连接拖住。
HTTP_TIMEOUT_SECONDS = 10.0
#: 第三方 JSON 响应的上限。正常 userinfo 只有几 KB,这个值只用来挡异常大的响应。
MAX_RESPONSE_BYTES = 256 * 1024
USER_AGENT = "MosaelCloud/0.1 (+https://mosael.com)"


class OAuthProviderError(Exception):
    """第三方明确拒绝或没正常回话。`code` 是 OAuth 错误码,`detail` 只进日志。"""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class ProviderIdentity:
    """第三方告诉我们"这是谁"。`email_verified` 必须是对方明确给出的 true。"""

    provider_user_id: str
    email: str
    email_verified: bool
    display_name: str = ""


class OAuthProvider(Protocol):
    """一个第三方登录实现。配置在调用时传入,provider 对象本身不带密钥。"""

    name: str

    def authorize_url(
        self, *, config: CloudConfig, redirect_uri: str, state: str, code_challenge: str
    ) -> str: ...

    def exchange_code(
        self, *, config: CloudConfig, code: str, redirect_uri: str, code_verifier: str
    ) -> str: ...

    def fetch_identity(self, *, config: CloudConfig, access_token: str) -> ProviderIdentity: ...


def new_code_verifier() -> str:
    """PKCE 的 verifier:43~128 个 unreserved 字符。`token_urlsafe(64)` 给 86 个。"""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """S256 challenge:base64url(sha256(verifier)),去掉 padding。"""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ---------------------------------------------------------------------------
# HTTP 小工具
# ---------------------------------------------------------------------------


def _request_json(request: urllib.request.Request) -> object:
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as failure:
        code, detail = _error_body(failure)
        raise OAuthProviderError(code, detail) from failure
    except (urllib.error.URLError, TimeoutError, OSError) as failure:
        raise OAuthProviderError("unreachable", type(failure).__name__) from failure

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as failure:
        raise OAuthProviderError("invalid_response", type(failure).__name__) from failure


def _error_body(failure: urllib.error.HTTPError) -> tuple[str, str]:
    """从 OAuth 的标准错误体里取 `error` / `error_description`;取不到就给 HTTP 状态。"""
    fallback = ("http_error", f"HTTP {failure.code}")
    try:
        body = json.loads(failure.read(MAX_RESPONSE_BYTES).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return fallback
    if not isinstance(body, dict):
        return fallback
    return (
        str(body.get("error") or fallback[0]),
        str(body.get("error_description") or body.get("message") or fallback[1]),
    )


def _post_form(url: str, fields: dict[str, str]) -> object:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode("ascii"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    return _request_json(request)


def _get_json(url: str, headers: dict[str, str]) -> object:
    request = urllib.request.Request(url, method="GET", headers={**headers, "User-Agent": USER_AGENT})
    return _request_json(request)


def _access_token(payload: object, provider: str) -> str:
    if not isinstance(payload, dict) or not payload.get("access_token"):
        code = payload.get("error", "token_missing") if isinstance(payload, dict) else "invalid_response"
        raise OAuthProviderError(str(code), f"{provider} token response did not include access_token")
    return str(payload["access_token"])


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------


class GitHubProvider:
    """GitHub OAuth App。邮箱必须从 `/user/emails` 取,`/user.email` 可能是空或未验证。"""

    name = "github"
    AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    USER_URL = "https://api.github.com/user"
    EMAILS_URL = "https://api.github.com/user/emails"
    SCOPE = "read:user user:email"

    def authorize_url(
        self, *, config: CloudConfig, redirect_uri: str, state: str, code_challenge: str
    ) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": config.github_client_id,
                "redirect_uri": redirect_uri,
                "scope": self.SCOPE,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "allow_signup": "true",
            }
        )
        return f"{self.AUTHORIZE_URL}?{query}"

    def exchange_code(
        self, *, config: CloudConfig, code: str, redirect_uri: str, code_verifier: str
    ) -> str:
        payload = _post_form(
            self.TOKEN_URL,
            {
                "client_id": config.github_client_id,
                "client_secret": config.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        return _access_token(payload, self.name)

    def fetch_identity(self, *, config: CloudConfig, access_token: str) -> ProviderIdentity:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        user = _get_json(self.USER_URL, headers)
        if not isinstance(user, dict) or user.get("id") is None:
            raise OAuthProviderError("invalid_response", "github /user had no id")

        emails = _get_json(self.EMAILS_URL, headers)
        if not isinstance(emails, list):
            emails = []
        verified = [
            item
            for item in emails
            if isinstance(item, dict) and item.get("verified") is True and item.get("email")
        ]
        primary = next((item for item in verified if item.get("primary") is True), None)
        chosen = primary or (verified[0] if verified else None)
        return ProviderIdentity(
            provider_user_id=str(user["id"]),
            email=str(chosen["email"]).strip().lower() if chosen else "",
            email_verified=chosen is not None,
            display_name=str(user.get("name") or user.get("login") or ""),
        )


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


class GoogleProvider:
    """Google OAuth 2.0 / OIDC。不验 id_token 的签名,身份直接取 userinfo(同样是 TLS 通道)。"""

    name = "google"
    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
    SCOPE = "openid email profile"

    def authorize_url(
        self, *, config: CloudConfig, redirect_uri: str, state: str, code_challenge: str
    ) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": config.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": self.SCOPE,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return f"{self.AUTHORIZE_URL}?{query}"

    def exchange_code(
        self, *, config: CloudConfig, code: str, redirect_uri: str, code_verifier: str
    ) -> str:
        payload = _post_form(
            self.TOKEN_URL,
            {
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        return _access_token(payload, self.name)

    def fetch_identity(self, *, config: CloudConfig, access_token: str) -> ProviderIdentity:
        profile = _get_json(self.USERINFO_URL, {"Authorization": f"Bearer {access_token}"})
        if not isinstance(profile, dict) or not profile.get("sub"):
            raise OAuthProviderError("invalid_response", "google userinfo had no sub")
        return ProviderIdentity(
            provider_user_id=str(profile["sub"]),
            email=str(profile.get("email") or "").strip().lower(),
            email_verified=profile.get("email_verified") is True,
            display_name=str(profile.get("name") or ""),
        )


def default_providers() -> dict[str, OAuthProvider]:
    """生产装配用的两家 provider。是否"已启用"由 `CloudConfig` 决定,不是由这里决定。"""
    return {"github": GitHubProvider(), "google": GoogleProvider()}
