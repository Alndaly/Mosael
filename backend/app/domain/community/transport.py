"""和社区服务说话的那一层:地址怎么拼、错误体怎么读、HTTP 客户端从哪来。

**接口前缀只在这里拼一次**(ADR 0026「API 约定」:`/api/community/v1`)。部署设置里存的是站点根
(`https://mosael.com`),因为那是管理员在浏览器里打开的地址;接口、设备授权页、「我的分享」都从它推出来。

`make_client` 是唯一造 HTTP 客户端的地方 —— 测试把它换成一个装着假社区服务的 `httpx.MockTransport`。
不带重试:创建条目、提交快照都不是幂等的,重放一次就多一条;上传单个文件的重试在 shares 里显式做。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

API_PREFIX = "/api/community/v1"
#: 普通请求的超时。上传单个文件另给(见 shares.UPLOAD_TIMEOUT_SECONDS)。
TIMEOUT_SECONDS = 30.0


def make_client(*, timeout: float = TIMEOUT_SECONDS) -> httpx.Client:
    """一个新的 HTTP 客户端。`trust_env` 保持默认:出站代理由 domain/network 写进进程环境,这里跟着走。"""
    return httpx.Client(timeout=timeout, follow_redirects=True)


def api_url(origin: str, path: str) -> str:
    """站点根 + 接口前缀 + 路径。`path` 以 `/` 开头(`/auth/refresh`)。"""
    return f"{origin.rstrip('/')}{API_PREFIX}{path}"


def absolute(origin: str, url: str) -> str:
    """服务端给的地址可能是相对的(`/api/community/v1/uploads/…`、`/zh/b/abc`):补成绝对地址。"""
    return urljoin(origin.rstrip("/") + "/", url)


def error_of(response: httpx.Response) -> tuple[str, str]:
    """`{"error": {"code": …, "message": …}}` → (code, message)。不是这个形状就回 ("", "")。"""
    try:
        body: Any = response.json()
    except ValueError:
        return "", ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "", ""
    return str(error.get("code") or ""), str(error.get("message") or "")
