"""本地后端访问 MosaelCloud 的 HTTP 客户端:社区分享的只读反代。

桌面端不直接调 Cloud(Cloud 只接受官网同源、不开 CORS),社区分享的读请求经本地后端转发:

    渲染层 → 本地后端 /api/cloud/v1/shares/* → MosaelCloud /shares/*

云地址、`RetryingClient`、超时和异常映射只有 `_request_json` 这一份,`post_json` 和 `get_json`
都从它出。**契约是"照 Cloud 的原样交回来"**:状态码是它的,JSON 也逐字段是它的,不替它翻译。

云端不可达或被拒时,抛 `CloudUnavailable` / `CloudBindingError`;本地登录态与本地账号**完全不动**。
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.http_retry import RetryingClient

#: 一次 Cloud 请求的等待上限。社区反代超时会翻成 504,不把前端的请求一起拖住。
TIMEOUT_SECONDS = 10.0


class CloudBindingError(Exception):
    """Cloud 明确拒绝(或本部署没配 Cloud):带状态码、机器码和一句给人看的话。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class CloudUnavailable(Exception):
    """连不上 Cloud。**不是**本地身份问题 —— 本地照常登录。"""


class CloudTimeout(CloudUnavailable):
    """连上了,但 Cloud 没在 `TIMEOUT_SECONDS` 内答完。

    **单独一种,因为经本地反代出去时它该说 504**:504 是"上游慢",503 是"到不了";两者对用户的
    处置差不多(等一等再试),但把慢说成到不了会让人去查网络。
    """


def _request_json(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list]:
    """向 Cloud 发一次请求,把**远端原样的**状态码和 JSON 交回来。

    云地址、`RetryingClient`、超时、异常映射只写在这一条里 —— 多写一份,迟早一处改了、另一处没改。

    `payload is None` 走 GET,否则走带 JSON 体的 POST。远端不是 JSON(网关的 HTML 错误页)时回空
    dict,状态码仍然照原样交出去。
    """
    base = settings.cloud_url.strip().rstrip("/")
    if not base:
        raise CloudBindingError(
            503,
            "cloud_not_configured",
            "MosaelCloud is not configured for this deployment (MOSAEL_CLOUD_URL).",
        )
    try:
        # 后端往外发 HTTP 一律经 RetryingClient:出站检查装在它的传输层上(见 core/outbound_guard)。
        with RetryingClient(timeout=TIMEOUT_SECONDS, max_retries=0) as client:
            if payload is None:
                response = client.get(f"{base}{path}")
            else:
                response = client.post(f"{base}{path}", json=payload)
    except httpx.TimeoutException as exc:
        raise CloudTimeout(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise CloudUnavailable(str(exc)) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, (dict, list)) else {}


def post_json(path: str, payload: dict) -> tuple[int, dict]:
    """向 Cloud 发一次 JSON POST。测试会替换这个函数,不去碰网络。"""
    status, body = _request_json("POST", path, payload)
    return status, body if isinstance(body, dict) else {}


def get_json(path: str) -> tuple[int, dict | list]:
    """向 Cloud 发一次只读 GET。**和 `post_json` 共用云地址、客户端、超时和异常映射。**

    测试会替换这个函数,不去碰网络。返回值**不做业务解释**:状态码和回包原样交给调用方 ——
    社区分享的反代要的就是这个,它不替 Cloud 把 404 说成"分享不存在"(那是界面的事)。
    """
    return _request_json("GET", path)
