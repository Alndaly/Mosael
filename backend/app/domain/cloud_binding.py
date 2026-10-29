"""本地后端访问 MosaelCloud 的 HTTP 客户端,以及桌面端的云端登录会话。

桌面端不直接调 Cloud(Cloud 只接受官网同源、不开 CORS),所有请求经本地后端转发:

    渲染层 → 本地后端 /api/cloud/v1/* → MosaelCloud /api/cloud/v1/*

云地址、`RetryingClient`、超时和异常映射只有 `request_json` 这一条链,`get_json` / `post_json`
都从它出。**契约是"照 Cloud 的原样交回来"**:状态码是它的,JSON 也逐字段是它的,不替它翻译。

登录成功后,Cloud 下发的会话 cookie 按本地用户存进 `cloud_login`(`cookie_value` 是加密列),
之后每一次转发自动带上它 —— 渲染层从头到尾看不到 cookie 值。本地登录态与本地账号**完全不动**。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.i18n import tr
from app.core.http_retry import RetryingClient
from app.db.model_base import now
from app.db.models import CloudLogin

logger = logging.getLogger(__name__)

#: 一次 Cloud 请求的等待上限。社区反代超时会翻成 504,不把前端的请求一起拖住。
TIMEOUT_SECONDS = 10.0

#: Cloud 的会话活 30 天(cloud/config.py 的 `session_ttl_days`)。`Set-Cookie` 没带 `Max-Age`
#: 时按这个算 —— 不把"不知道"当成永不过期。
DEFAULT_COOKIE_TTL = timedelta(days=30)


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
    """Cloud 发下来的一枚会话 cookie。名字跟着 Cloud 走,不写死。"""

    name: str
    value: str
    max_age: int | None = None


@dataclass(frozen=True)
class CloudReply:
    """一次 Cloud 请求的结果:远端原样的状态码与 JSON,外加它下发的会话 cookie(如果有)。"""

    status: int
    body: dict | list
    #: `Set-Cookie` 里那枚非空的 cookie。登录之外的接口一般没有;有了也只在登录那几条路上落库。
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


def _request_headers(base: str, session: CloudCookie | None) -> dict[str, str]:
    """转发时必须带的头:同源头 + 已登录时的会话 cookie。

    Cloud 的写请求过一道同源闸(`cloud/app.py::_cross_site`):`Sec-Fetch-Site: cross-site` 直接拒,
    `Origin` / `Referer` 落在别的站点也拒(缺头不拦,但那是"不是浏览器"的豁免,不该拿来当策略)。
    所以这里按 Cloud **自己那个 origin** 给全三样。
    """
    origin = _origin(base)
    headers = {"Accept": "application/json", "Sec-Fetch-Site": "same-origin"}
    if origin:
        headers["Origin"] = origin
        headers["Referer"] = f"{origin}/"
    if session is not None:
        headers["Cookie"] = f"{session.name}={session.value}"
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
            raw_max_age = morsel["max-age"]
            try:
                max_age = int(raw_max_age) if raw_max_age else None
            except ValueError:
                max_age = None
            return CloudCookie(name=name, value=morsel.value, max_age=max_age)
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
    session: CloudCookie | None = None,
) -> CloudReply:
    """向 Cloud 发一次请求,把**远端原样的**状态码、JSON 和下发 cookie 交回来。

    云地址、`RetryingClient`、超时、异常映射、同源头、会话 cookie 只写在这一条里 —— 多写一份,
    迟早一处改了、另一处没改。`payload is None` 时不带 JSON 体(读请求与无体的写请求)。

    远端不是 JSON(网关的 HTML 错误页)时回空 dict,状态码仍然照原样交出去。
    """
    require_configured()
    base = settings.cloud_url.strip().rstrip("/")
    headers = _request_headers(base, session)
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


# ---------------------------------------------------------------- 本地那一行会话


def load_login(db: Session, user_id: str) -> CloudLogin | None:
    """这个本地用户存着的云登录;过期了就**当场删掉**,当作没登录。

    过期的那一行留着只会让下一次转发带上一枚必然被拒的 cookie —— 界面看到的 401 和"没登录"
    一样,但库里多了一行没人清。
    """
    row = db.get(CloudLogin, user_id)
    if row is None:
        return None
    if row.expires_at <= now():
        db.delete(row)
        db.flush()
        return None
    return row


def save_login(db: Session, user_id: str, *, email: str, cookie: CloudCookie) -> CloudLogin:
    """登录成功后把这一枚 cookie 落库。**同一个本地用户只留一行**:重新登录就是覆盖。"""
    ttl = timedelta(seconds=cookie.max_age) if cookie.max_age and cookie.max_age > 0 else DEFAULT_COOKIE_TTL
    row = db.get(CloudLogin, user_id)
    if row is None:
        row = CloudLogin(user_id=user_id)
        db.add(row)
    row.email = email
    row.cookie_name = cookie.name
    row.cookie_value = cookie.value
    row.expires_at = now() + ttl
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


def cookie_of(row: CloudLogin) -> CloudCookie:
    """把库里那一行变回转发的 `Cookie` 头要的形状。"""
    return CloudCookie(name=row.cookie_name, value=row.cookie_value)


def expires_at_of(row: CloudLogin) -> datetime:
    return row.expires_at
