"""可灵开放平台的连接:根地址、鉴权头、带重试的客户端。

视频(连同挂在它连接上的数字人、对口型、主体库)和音效是同一个平台、同一套鉴权,所以连接只写
这一份。官方账号用 AccessKey + SecretKey 现签 JWT;控制台生成的 API Key、以及一些兼容网关收的
是裸 Bearer —— 连接上填没填 Secret Key 决定走哪条,调用方不分支。

鉴权文档:https://kling.ai/document-api/api/get-started/authentication
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationAdapterError
from app.core.http_retry import RetryingClient

KLING_BASE = "https://api.klingai.com"


def client(context: GenerationAdapterContext) -> RetryingClient:
    """连上这个用户的可灵。鉴权头每次现签(JWT 带过期时间)—— 取回时隔了一次重启,旧的那张早过期了。"""
    if not context.api_key:
        raise GenerationAdapterError("providerErr_klingKeyMissing")
    headers = {"Authorization": auth_header(context), "Content-Type": "application/json"}
    return RetryingClient(base_url=(context.base_url or KLING_BASE).rstrip("/"), timeout=60, headers=headers, follow_redirects=True)


def auth_header(context: GenerationAdapterContext) -> str:
    secret_key = str(context.options.get("secret_key") or "")
    if not secret_key:
        return f"Bearer {context.api_key}"
    now = int(time.time())
    token = _jwt_hs256(
        {"iss": context.api_key, "exp": now + 1800, "nbf": now - 5},
        secret_key,
    )
    return f"Bearer {token}"


def _jwt_hs256(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = ".".join([_b64url_json(header), _b64url_json(payload)])
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _b64url_json(value: dict[str, Any]) -> str:
    return _b64url(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
