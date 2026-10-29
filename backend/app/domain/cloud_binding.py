"""本地后端访问 MosaelCloud 的 HTTP 客户端,以及桌面端的云端登录会话。

桌面端不直接调 Cloud(Cloud 只接受官网同源、不开 CORS),所有请求经本地后端转发:

    渲染层 → 本地后端 /api/cloud/v1/* → MosaelCloud /api/cloud/v1/*

云地址、`RetryingClient`、超时和异常映射只有 `request_json` 这一条链,`get_json` / `post_json`
都从它出。**契约是"照 Cloud 的原样交回来"**:状态码是它的,JSON 也逐字段是它的,不替它翻译。

**桌面端只拿一枚设备令牌说话**(ADR 0088 第 1 步)。登录那一刻 Cloud 下发会话 cookie,本地后端立刻用它
换一枚设备令牌(`POST /device-tokens`),再退掉那份会话 —— cookie 只活在登录这一跳里。令牌按本地用户存进
`cloud_login`(`device_token` 是加密列),之后每一次转发带 `Authorization: Bearer`,渲染层从头到尾看不到它。
令牌不过期,失效靠吊销:Cloud 回 401 就清掉本地那一行。本地登录态与本地账号**完全不动**。
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import tr
from app.core.http_retry import RetryingClient
from app.core.outbound_guard import OutboundBlocked
from app.db.model_base import now
from app.db.models import CloudLogin

logger = logging.getLogger(__name__)

#: 一次 Cloud 请求的等待上限。社区反代超时会翻成 504,不把前端的请求一起拖住。
TIMEOUT_SECONDS = 10.0

#: Cloud 那边设备名的上限(cloud/domain/device_tokens.NAME_MAX)。
DEVICE_NAME_MAX = 80


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


@dataclass(frozen=True)
class CloudCookie:
    """Cloud 在登录响应里发下来的一枚会话 cookie。**只用来换设备令牌**,不落库。名字跟着 Cloud 走,不写死。"""

    name: str
    value: str


@dataclass(frozen=True)
class DeviceToken:
    """Cloud 签给这台桌面端的设备令牌。`secret` 是原文(`mct_…`),只进加密列与 Bearer 头。"""

    id: str
    secret: str


@dataclass(frozen=True)
class CloudReply:
    """一次 Cloud 请求的结果:远端原样的状态码与 JSON,外加它下发的会话 cookie(如果有)。"""

    status: int
    body: dict | list
    #: `Set-Cookie` 里那枚非空的 cookie。只有登录那几条路有,用来换设备令牌。
    cookie: CloudCookie | None = None


def _origin(base: str) -> str:
    """`https://mosael.com/api/cloud/v1` → `https://mosael.com`。

    Cloud 的同源校验比的是 **origin**,不是完整 URL(`cloud/app.py::_origin_of` 只取
    scheme + host[:port])。拿整条 base 去当 Origin,长得像却永远对不上。
    """
    split = urlsplit(base)
    if not split.scheme or not split.netloc:
        return ""
    return f"{split.scheme}://{split.netloc}"


def _request_headers(base: str, *, cookie: CloudCookie | None, device_token: str | None) -> dict[str, str]:
    """转发时必须带的头:同源头 + 一份身份(登录那一跳是 cookie,之后都是设备令牌)。

    Cloud 的写请求过一道同源闸(`cloud/app.py::_cross_site`):`Sec-Fetch-Site: cross-site` 直接拒,
    `Origin` / `Referer` 落在别的站点也拒(缺头不拦,但那是"不是浏览器"的豁免,不该拿来当策略)。
    所以这里按 Cloud **自己那个 origin** 给全三样。
    """
    origin = _origin(base)
    headers = {"Accept": "application/json", "Sec-Fetch-Site": "same-origin"}
    if origin:
        headers["Origin"] = origin
        headers["Referer"] = f"{origin}/"
    if cookie is not None:
        headers["Cookie"] = f"{cookie.name}={cookie.value}"
    if device_token is not None:
        headers["Authorization"] = f"Bearer {device_token}"
    return headers


def _session_cookie(headers: httpx.Headers) -> CloudCookie | None:
    """从 `Set-Cookie` 里挑出**那一枚**会话 cookie;没有就 None。

    登录响应只下发一枚会话 cookie。删除用的空值 cookie(`Max-Age=0`)不算 —— 那是退出登录,
    不是一次新的登录。
    """
    for header in headers.get_list("set-cookie"):
        jar = SimpleCookie()
        try:
            jar.load(header)
        except CookieError:
            continue
        for name, morsel in jar.items():
            if not morsel.value:
                continue
            return CloudCookie(name=name, value=morsel.value)
    return None


def configuration_problem() -> str:
    """这个部署的 Cloud 配置有什么问题:空串 = 没问题;否则是机器码。**只看本地配置,不出网、不写日志**
    (`/api/health` 每秒级被壳轮询,也读它)。

    - `cloud_not_configured`:`MOSAEL_CLOUD_URL` 被显式设成空 —— 这个部署不接 Cloud(产品默认接官方的,见 config);
    - `cloud_misconfigured`:地址少了 `/api/cloud/v1` 后缀。转发是 `base + "/shares"` 这样拼的,少了后缀请求会打到
      站点根、云端回 404,表现为「登录完就掉线」—— 宁可当场说清楚。
    """
    url = settings.cloud_url.strip()
    if not url:
        return "cloud_not_configured"
    if not url.rstrip("/").endswith("/api/cloud/v1"):
        return "cloud_misconfigured"
    return ""


def require_configured() -> None:
    """接了 Cloud 才往下走;没接就抛 503,`code` 是 `configuration_problem` 的那个机器码。

    和 `request_json` 共用同一处判断与同一句话 —— 不允许别的路由自己再拼一句。**这句话会原样到界面上**,所以只说发生了什么、
    找谁;「改哪个环境变量」是部署管理员的事,写在日志里(和 docs/CLOUD_ACCOUNTS.md),不教每个用户去设环境变量。
    """
    problem = configuration_problem()
    if problem == "cloud_not_configured":
        raise CloudBindingError(503, problem, tr("routeErr_cloudNotConfigured"))
    if problem == "cloud_misconfigured":
        logger.warning(
            "MOSAEL_CLOUD_URL=%r 少了 /api/cloud/v1 后缀(例如 https://mosael.com/api/cloud/v1),MosaelCloud 不可用",
            settings.cloud_url,
        )
        raise CloudBindingError(503, problem, tr("routeErr_cloudMisconfigured"))


def request_json(
    method: str,
    path: str,
    payload: dict | list | None = None,
    *,
    cookie: CloudCookie | None = None,
    device_token: str | None = None,
) -> CloudReply:
    """向 Cloud 发一次请求,把**远端原样的**状态码、JSON 和下发 cookie 交回来。

    身份最多一份:`cookie` 只在登录那一跳(换令牌、退会话)用,其余都是 `device_token`。

    云地址、`RetryingClient`、超时、异常映射、同源头、身份头只写在这一条里 —— 多写一份,
    迟早一处改了、另一处没改。`payload is None` 时不带 JSON 体(读请求与无体的写请求)。

    远端不是 JSON(网关的 HTML 错误页)时回空 dict,状态码仍然照原样交出去。
    """
    if cookie is not None and device_token is not None:
        raise ValueError("pass either a cookie or a device token, not both")
    require_configured()
    base = settings.cloud_url.strip().rstrip("/")
    headers = _request_headers(base, cookie=cookie, device_token=device_token)
    try:
        # 后端往外发 HTTP 一律经 RetryingClient:出站检查装在它的传输层上(见 core/outbound_guard)。
        with RetryingClient(timeout=TIMEOUT_SECONDS, max_retries=0) as client:
            response = client.request(
                method.upper(), f"{base}{path}", json=payload, headers=headers
            )
    except httpx.TimeoutException as exc:
        raise CloudTimeout(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise CloudUnavailable(str(exc)) from exc
    except OutboundBlocked as exc:
        # 服务端部署把 Cloud 配成了内网地址、又没在「管理 → 内网访问」里放行:是部署的事,说清是哪个地址、怎么放行,
        # 不是一个 500。桌面版上部署配的地址不过这道检查(见 core/outbound_guard.checks)。
        raise CloudBindingError(503, "cloud_blocked", str(exc)) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    return CloudReply(
        status=response.status_code,
        body=body if isinstance(body, (dict, list)) else {},
        cookie=_session_cookie(response.headers),
    )


def _request_json(method: str, path: str, payload: dict | None = None) -> tuple[int, dict | list]:
    """旧签名:`(状态码, JSON)`。给只关心这两样的调用方 / 测试保留,内部仍走 `request_json`。"""
    reply = request_json(method, path, payload)
    return reply.status, reply.body


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


# ---------------------------------------------------------------- 设备令牌与本地那一行


def device_name() -> str:
    """报给 Cloud 的设备名:本机主机名(去掉 mDNS 的 `.local`)。只给用户在「我的设备」里认。"""
    host = socket.gethostname().strip().removesuffix(".local")
    return (host or "Mosael")[:DEVICE_NAME_MAX]


def exchange_for_device_token(cookie: CloudCookie) -> DeviceToken | None:
    """用登录刚拿到的会话换一枚设备令牌,再退掉那份会话。换不到就是 None(调用方报 502)。

    **退会话是尽力而为**:令牌已经到手,会话退不掉也只是在 Cloud 里多一行 30 天后自己过期的记录,
    不该让一次成功的登录失败。
    """
    reply = request_json("POST", "/device-tokens", {"name": device_name()}, cookie=cookie)
    token = reply.body.get("token") if isinstance(reply.body, dict) else None
    secret = reply.body.get("secret") if isinstance(reply.body, dict) else None
    if reply.status != 201 or not isinstance(token, dict) or not isinstance(secret, str) or not secret:
        return None
    try:
        request_json("POST", "/logout", {}, cookie=cookie)
    except CloudUnavailable:
        logger.info("换到设备令牌后退登录会话失败;会话到期会自己失效")
    return DeviceToken(id=str(token.get("id") or ""), secret=secret)


def load_login(db: Session, user_id: str) -> CloudLogin | None:
    """这个本地用户存着的云登录。令牌不过期 —— 没有"过期就删"这一步,失效由 Cloud 的 401 告诉我们。"""
    return db.get(CloudLogin, user_id)


def save_login(db: Session, user_id: str, *, email: str, token: DeviceToken) -> CloudLogin:
    """登录成功后把设备令牌落库。**同一个本地用户只留一行**:重新登录就是覆盖。"""
    row = db.get(CloudLogin, user_id)
    if row is None:
        row = CloudLogin(user_id=user_id)
        db.add(row)
    row.email = email
    row.device_token_id = token.id
    row.device_token = token.secret
    row.created_at = now()
    db.flush()
    return row


def drop_login(db: Session, user_id: str) -> None:
    """删掉这个本地用户的云登录。云端 401、主动退出、换账号都走这一条。"""
    row = db.get(CloudLogin, user_id)
    if row is None:
        return
    db.delete(row)
    db.flush()


def device_token_of(row: CloudLogin | None) -> str | None:
    """转发要带的 Bearer 令牌;没登录就是 None(按游客转发)。"""
    return row.device_token if row is not None else None
