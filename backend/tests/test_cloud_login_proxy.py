"""桌面端登录 MosaelCloud:**本地后端存云端会话 cookie,再替桌面端带上它**。

维护者原话:「桌面端和网站端本来就都可以独立登录」「桌面端也要可以通过邮箱账号密码等信息登录」,
存储方式定为「存 cookie」。于是这一层只做两件事:

1. **登录成功后把云端的 `Set-Cookie` 存进本地 `cloud_login`**(按本地用户一行,密文列),
   **不存密码**;响应里只回 `{email}`,cookie 值绝不回给渲染层;
2. 之后每一次转发**自动带上这一枚 cookie**(`_request_json` 那一条链),云端 401 就清行 + 回 401,
   让界面知道要重新登录。

不碰网络:云端用 `httpx.MockTransport` 打桩,断言的是**真正发出去的那个请求**。
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.domain import cloud_binding
from app.main import app
from tests.util import fresh_client

#: 必须带 `/api/cloud/v1` —— 转发是 `base + "/shares"` 拼的,少了后缀会打到站点根(见 require_configured)。
CLOUD_URL = "https://cloud.example/api/cloud/v1"
#: 同一台机器上的站点根 —— 云端看到的路径是去掉 `/api/cloud/v1` 之后的。
CLOUD_ORIGIN = "https://cloud.example"
COOKIE_NAME = "mosael_cloud_session"
COOKIE_VALUE = "tok-7f4b29c1d8e35a6079bc"
EMAIL = "alice@example.com"
PASSWORD = "correct horse battery staple"
LOGIN_COOKIE = (
    f"{COOKIE_NAME}={COOKIE_VALUE}; Path=/api/cloud/v1; Max-Age=2592000; "
    "HttpOnly; Secure; SameSite=lax"
)
CLOUD_ERROR = {
    "error": "invalid_credentials",
    "message": {
        "en": "Email or password is incorrect.",
        "zh": "邮箱或密码不正确。",
    },
}


def _all_strings(value) -> list[str]:
    """把一个 JSON 值里的**每一个字段名和值**都摊平 —— 断言 cookie 不在任何一处。"""
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            found.append(str(key))
            found.extend(_all_strings(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_all_strings(item))
    return found


class FakeCloud:
    """按顺序回放 `httpx.Response` / 异常,并记下每一个真正出站的 `httpx.Request`。"""

    def __init__(self) -> None:
        self.responses: list[httpx.Response | BaseException] = []
        self.requests: list[httpx.Request] = []

    def reply(self, status: int, body=None, *, headers: dict[str, str] | None = None) -> None:
        self.responses.append(httpx.Response(status, json=body, headers=headers))

    def reply_raw(self, response: httpx.Response) -> None:
        self.responses.append(response)

    def fail(self, error: BaseException) -> None:
        self.responses.append(error)

    def handler(self, request: httpx.Request) -> httpx.Response:
        # 云端自己看到的路径是去掉 `/api/cloud/v1` 之后的 —— 那份前缀属于**部署地址**(见 require_configured),
        # 不属于路由。记的时候剥掉,测试才能继续断言 `/shares` 这种"路由视角"的路径。
        routed = str(request.url).replace(CLOUD_URL, CLOUD_ORIGIN)
        self.requests.append(
            httpx.Request(request.method, routed, headers=request.headers, content=request.content)
        )
        if not self.responses:
            raise AssertionError(f"unexpected outbound request: {request.method} {request.url}")
        found = self.responses.pop(0)
        if isinstance(found, BaseException):
            raise found
        return found


@pytest.fixture
def cloud(monkeypatch) -> FakeCloud:
    """把云端整段换成内存传输:出站地址、方法、头、体都还经过真代码。"""
    fake = FakeCloud()
    transport = httpx.MockTransport(fake.handler)

    def factory(*args, **kwargs) -> httpx.Client:
        return httpx.Client(transport=transport, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL)
    monkeypatch.setattr(cloud_binding, "RetryingClient", factory)
    return fake


def login(client, cloud: FakeCloud, *, email: str = EMAIL, password: str = PASSWORD):
    cloud.reply(200, {"user": {"email": email}}, headers={"set-cookie": LOGIN_COOKIE})
    response = client.post("/api/cloud/v1/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


def rows() -> list[tuple]:
    with engine.begin() as connection:
        return list(connection.execute(text("SELECT * FROM cloud_login")))


# ---------------------------------------------------------------- ① 登录:存 cookie、只回 email


def test_login_stores_the_cloud_cookie_and_returns_only_the_email(cloud: FakeCloud) -> None:
    client = fresh_client()
    response = login(client, cloud)

    #: 响应里只有邮箱 —— **cookie 值不在任何字段名、任何值里**。
    assert response.json() == {"email": EMAIL}
    strings = _all_strings(response.json())
    assert not any(COOKIE_VALUE in one for one in strings), strings
    assert COOKIE_VALUE not in response.text
    #: 连响应头里也不许把它带回来(Cloud 的 Set-Cookie 只该落进本地那一行)。
    assert "set-cookie" not in response.headers
    assert COOKIE_VALUE not in str(dict(response.headers))

    #: 表里确实有一行,而且是**密文**。
    with SessionLocal() as db:
        from app.db.models import CloudLogin

        stored = db.query(CloudLogin).one()
        assert stored.email == EMAIL
        assert stored.cookie_name == COOKIE_NAME
        assert stored.cookie_value == COOKIE_VALUE
        assert COOKIE_VALUE not in str(rows()), "cookie 原文出现在盘上"


def test_login_never_stores_the_password(cloud: FakeCloud) -> None:
    client = fresh_client()
    response = login(client, cloud)

    assert PASSWORD not in response.text
    assert PASSWORD not in str(rows()), "密码落进了 cloud_login"
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(cloud_login)"))}
    assert "password" not in columns


def test_a_failed_login_keeps_the_human_message_and_stores_nothing(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(401, CLOUD_ERROR)
    response = client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": "wrong"})

    assert response.status_code == 401, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_credentials"
    #: 后端文案原样交给界面(中英按 Accept-Language 挑一条),不是只有一个 code。
    assert detail["message"]
    assert rows() == []


def test_a_rate_limited_login_keeps_its_message(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(
        429,
        {"error": "too_many_requests", "message": {"en": "Too many requests.", "zh": "操作太频繁。"}},
    )
    response = client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 429, response.text
    assert response.json()["detail"]["code"] == "too_many_requests"
    assert response.json()["detail"]["message"]


# ---------------------------------------------------------------- ② 之后的读带上 cookie


def test_logged_in_reads_carry_the_stored_cookie(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)

    cloud.reply(200, {"user": {"email": EMAIL}})
    response = client.get("/api/cloud/v1/me")

    assert response.status_code == 200, response.text
    assert response.json() == {"email": EMAIL}
    outbound = cloud.requests[-1]
    assert outbound.headers.get("cookie") == f"{COOKIE_NAME}={COOKIE_VALUE}"

    #: 同样的断言走一条**公开读**的分享详情:登录之后它自动以登录身份读。
    cloud.reply(200, {"id": "share-1", "title": "Space Opera"})
    assert client.get("/api/cloud/v1/shares/share-1").status_code == 200
    assert cloud.requests[-1].headers.get("cookie") == f"{COOKIE_NAME}={COOKIE_VALUE}"


def test_a_guest_read_does_not_invent_a_cookie(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"id": "share-1"})

    assert client.get("/api/cloud/v1/shares/share-1").status_code == 200
    assert "cookie" not in cloud.requests[-1].headers


# ---------------------------------------------------------------- ③ 云端 401:清行 + 401


def test_a_cloud_401_clears_the_local_row_and_answers_401(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    assert rows()

    cloud.reply(401, {"error": "not_authenticated", "message": {"en": "Sign in.", "zh": "请登录。"}})
    response = client.get("/api/cloud/v1/me")

    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "not_authenticated"
    assert rows() == [], "云端说会话没了,本地那一行还留着"


# ---------------------------------------------------------------- ④ 退出登录


def test_logout_calls_cloud_and_deletes_the_row(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)

    cloud.reply_raw(httpx.Response(204, headers={"set-cookie": f"{COOKIE_NAME}=; Max-Age=0"}))
    response = client.post("/api/cloud/v1/logout")

    assert response.status_code == 204, response.text
    assert rows() == []
    outbound = cloud.requests[-1]
    assert (outbound.method, outbound.url.path) == ("POST", "/logout")
    assert outbound.headers.get("cookie") == f"{COOKIE_NAME}={COOKIE_VALUE}"


# ---------------------------------------------------------------- ⑤ 同源头


def _cloud_accepts(headers: httpx.Headers, allowed_origin: str) -> bool:
    """`cloud/app.py::_cross_site` 的判据,原样搬过来 —— 断言的是"那边会不会放行"。"""
    if headers.get("sec-fetch-site", "").lower() == "cross-site":
        return False
    candidate = headers.get("origin") or headers.get("referer") or ""
    if not candidate:
        return False  # 这里特意比云端更严:转发的写请求**必须**带一个能对上的 Origin
    split = urlsplit(candidate)
    return f"{split.scheme}://{split.netloc}" == allowed_origin


def test_outbound_write_requests_pass_the_cloud_same_origin_gate(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    outbound = cloud.requests[-1]

    assert outbound.method == "POST"
    # 比的是**站点根**(Origin 没有路径),不是带 `/api/cloud/v1` 的部署地址。
    assert _cloud_accepts(outbound.headers, CLOUD_ORIGIN), dict(outbound.headers)
    assert outbound.headers["sec-fetch-site"] != "cross-site"


# ---------------------------------------------------------------- ⑥ 没配 Cloud / 回归


def test_without_cloud_url_every_new_route_says_not_configured(monkeypatch) -> None:
    client = fresh_client()
    monkeypatch.setattr(settings, "cloud_url", "")

    expected: str | None = None
    for method, path, body in (
        ("post", "/api/cloud/v1/login", {"email": EMAIL, "password": PASSWORD}),
        ("post", "/api/cloud/v1/login/code", {"email": EMAIL}),
        ("post", "/api/cloud/v1/login/code/verify", {"email": EMAIL, "code": "123456"}),
        ("post", "/api/cloud/v1/logout", None),
        ("get", "/api/cloud/v1/me", None),
        ("get", "/api/cloud/v1/shares/share-1", None),
    ):
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 503, (method, path, response.text)
        assert response.json()["detail"]["code"] == "cloud_not_configured"
        expected = expected or response.json()["detail"]["message"]
        assert response.json()["detail"]["message"] == expected
    #: 这句话会原样到每个用户的设置页上:只说找谁,不教人设环境变量(ADR 0088 §0)。
    assert expected and "MOSAEL_CLOUD_URL" not in expected


def test_health_says_whether_this_deployment_has_cloud_without_signing_in(monkeypatch) -> None:
    """`/api/health` 的 `cloud` 只读本地配置、不出网、不要登录:打包冒烟靠它确认安装版默认接上了 Cloud。"""
    anonymous = TestClient(app)
    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL)
    assert anonymous.get("/api/health").json()["cloud"] == "configured"
    monkeypatch.setattr(settings, "cloud_url", "")
    assert anonymous.get("/api/health").json()["cloud"] == "cloud_not_configured"
    monkeypatch.setattr(settings, "cloud_url", "https://cloud.example")
    assert anonymous.get("/api/health").json()["cloud"] == "cloud_misconfigured"


def test_the_product_default_is_the_official_cloud(monkeypatch) -> None:
    """安装版不注入任何环境变量:不设 `MOSAEL_CLOUD_URL` 时就该接官方 Cloud(ADR 0088 §0);显式设空 = 不接。

    此前默认空串,每一个安装版都显示「没接 MosaelCloud,去设环境变量」。测试环境在 conftest 里把它显式设空(不出网),
    所以这里先拿掉那个变量,只读代码里的默认值。"""
    from app.core.config import OFFICIAL_CLOUD_URL, Settings

    monkeypatch.delenv("MOSAEL_CLOUD_URL", raising=False)
    assert Settings(_env_file=None).cloud_url == OFFICIAL_CLOUD_URL == "https://mosael.com/api/cloud/v1"
    monkeypatch.setenv("MOSAEL_CLOUD_URL", "")
    assert Settings(_env_file=None).cloud_url == ""
    monkeypatch.setenv("MOSAEL_CLOUD_URL", "http://127.0.0.1:8000/api/cloud/v1")
    assert Settings(_env_file=None).cloud_url == "http://127.0.0.1:8000/api/cloud/v1"


def test_the_share_detail_proxy_still_reads(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"id": "share-1", "title": "Space Opera", "unknown_future_field": [1, 2]})

    response = client.get("/api/cloud/v1/shares/share-1")

    assert response.status_code == 200
    assert response.json()["unknown_future_field"] == [1, 2]


# ---------------------------------------------------------------- 全量端点


PROXIED = [
    ("post", "/api/cloud/v1/login/code", {"email": EMAIL}, "POST", "/login/code"),
    ("get", "/api/cloud/v1/me", None, "GET", "/me"),
    ("get", "/api/cloud/v1/shares", None, "GET", "/shares"),
    ("post", "/api/cloud/v1/shares", {"kind": "workflow", "title": "T"}, "POST", "/shares"),
    ("post", "/api/cloud/v1/shares/share-1/like", {}, "POST", "/shares/share-1/like"),
    ("delete", "/api/cloud/v1/shares/share-1/like", None, "DELETE", "/shares/share-1/like"),
    ("post", "/api/cloud/v1/shares/share-1/favorite", {}, "POST", "/shares/share-1/favorite"),
    ("delete", "/api/cloud/v1/shares/share-1/favorite", None, "DELETE", "/shares/share-1/favorite"),
    ("get", "/api/cloud/v1/shares/share-1/comments", None, "GET", "/shares/share-1/comments"),
    ("post", "/api/cloud/v1/shares/share-1/comments", {"body": "nice"}, "POST", "/shares/share-1/comments"),
    ("delete", "/api/cloud/v1/shares/share-1/comments/c-1", None, "DELETE", "/shares/share-1/comments/c-1"),
    ("delete", "/api/cloud/v1/shares/share-1", None, "DELETE", "/shares/share-1"),
    ("get", "/api/cloud/v1/notifications", None, "GET", "/notifications"),
    ("get", "/api/cloud/v1/notifications/unread-count", None, "GET", "/notifications/unread-count"),
    ("post", "/api/cloud/v1/notifications/read", {"ids": ["n-1"]}, "POST", "/notifications/read"),
    ("get", "/api/cloud/v1/shares/share-1/payload", None, "GET", "/shares/share-1/payload"),
    ("post", "/api/cloud/v1/shares/share-1/download", None, "POST", "/shares/share-1/download"),
    ("get", "/api/cloud/v1/users/alice/shares", None, "GET", "/users/alice/shares"),
]


@pytest.mark.parametrize(("method", "path", "body", "out_method", "out_path"), PROXIED)
def test_every_listed_endpoint_is_proxied(
    cloud: FakeCloud, method, path, body, out_method, out_path
) -> None:
    client = fresh_client()
    login(client, cloud)
    cloud.reply_raw(httpx.Response(200, json={"ok": True}))

    response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)

    assert response.status_code == 200, (method, path, response.text)
    outbound = cloud.requests[-1]
    assert (outbound.method, outbound.url.path) == (out_method, out_path)
    assert outbound.headers.get("cookie") == f"{COOKIE_NAME}={COOKIE_VALUE}"


def test_a_write_body_is_forwarded_field_for_field(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    cloud.reply(201, {"comment": {"id": "c-1"}})

    response = client.post("/api/cloud/v1/shares/share-1/comments", json={"body": "不错"})

    assert response.status_code == 201
    assert cloud.requests[-1].content == '{"body":"不错"}'.encode()


def test_query_parameters_survive_the_relay(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    cloud.reply(200, {"items": [], "next_cursor": None})

    assert client.get("/api/cloud/v1/shares?q=space&kind=workflow&sort=new&limit=5").status_code == 200
    outbound = cloud.requests[-1]
    assert outbound.url.path == "/shares"
    assert outbound.url.params["q"] == "space"
    assert outbound.url.params["limit"] == "5"


# ---------------------------------------------------------------- 验证码两步


def test_the_login_code_flow_stores_the_cookie_on_verify(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"sent": True})
    assert client.post("/api/cloud/v1/login/code", json={"email": EMAIL}).status_code == 200
    assert (cloud.requests[-1].method, cloud.requests[-1].url.path) == ("POST", "/login/code")

    cloud.reply(200, {"user": {"email": EMAIL}}, headers={"set-cookie": LOGIN_COOKIE})
    response = client.post("/api/cloud/v1/login/code/verify", json={"email": EMAIL, "code": "123456"})

    assert response.status_code == 200, response.text
    assert response.json() == {"email": EMAIL}
    assert COOKIE_VALUE not in response.text
    assert len(rows()) == 1


def test_me_without_a_stored_login_is_401_without_touching_cloud(cloud: FakeCloud) -> None:
    client = fresh_client()

    response = client.get("/api/cloud/v1/me")

    assert response.status_code == 401
    assert cloud.requests == []
    assert rows() == []


def test_an_expired_stored_cookie_is_forgotten_before_it_is_used(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    with SessionLocal() as db:
        from app.db.models import CloudLogin

        row = db.query(CloudLogin).one()
        row.expires_at = row.created_at.replace(year=2000)
        db.commit()

    cloud.reply(401, {"error": "not_authenticated", "message": {"en": "Sign in.", "zh": "请登录。"}})
    assert client.get("/api/cloud/v1/me").status_code == 401
    assert rows() == []
