"""桌面端登录 MosaelCloud:**登录那一跳用会话换设备令牌,之后只拿令牌说话**(ADR 0088 第 1 步)。

维护者原话:「桌面端和网站端本来就都可以独立登录」「桌面端也要可以通过邮箱账号密码等信息登录」。
这一层只做两件事:

1. **登录成功后用云端的 `Set-Cookie` 换一枚设备令牌**(`POST /device-tokens`),随即退掉那份会话;
   令牌存进本地 `cloud_login`(按本地用户一行,密文列),**不存密码、不存 cookie**;响应里只回 `{email}`;
2. 之后每一次转发**带 `Authorization: Bearer`**(`request_json` 那一条链),云端 401 就清行 + 回 401,
   让界面知道要重新登录。

不碰网络:云端用 `httpx.MockTransport` 打桩,断言的是**真正发出去的那个请求**。
"""

from __future__ import annotations

import json
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
DEVICE_TOKEN_ID = "dt-1"
DEVICE_TOKEN = "mct_9c1d8e35a6079bc7f4b2"
BEARER = f"Bearer {DEVICE_TOKEN}"
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


GATEWAY_MODELS = {"object": "list", "data": [
    {"id": "deepseek-chat", "object": "model", "name": "DeepSeek V3", "max_output_tokens": 8000,
     "pricing": {"prompt": "0.002", "completion": "0.008", "currency": "CREDITS"}},
]}


def queue_successful_login(cloud: FakeCloud, *, email: str = EMAIL, models: dict | None = None) -> None:
    """一次成功登录在云端那一侧的四跳:登录发 cookie → cookie 换设备令牌 → 退掉那份会话 → 问网关目录(对齐「Mosael Cloud」连接)。"""
    cloud.reply(200, {"user": {"email": email}}, headers={"set-cookie": LOGIN_COOKIE})
    cloud.reply(201, {"token": {"id": DEVICE_TOKEN_ID, "name": "host"}, "secret": DEVICE_TOKEN})
    cloud.reply_raw(httpx.Response(204, headers={"set-cookie": f"{COOKIE_NAME}=; Max-Age=0"}))
    cloud.reply(200, models if models is not None else {"object": "list", "data": []})


def login(client, cloud: FakeCloud, *, email: str = EMAIL, password: str = PASSWORD):
    queue_successful_login(cloud, email=email)
    response = client.post("/api/cloud/v1/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


def rows() -> list[tuple]:
    with engine.begin() as connection:
        return list(connection.execute(text("SELECT * FROM cloud_login")))


# ---------------------------------------------------------------- ① 登录:换令牌、存令牌、只回 email


def test_login_exchanges_the_session_for_a_device_token_and_returns_only_the_email(cloud: FakeCloud) -> None:
    client = fresh_client()
    response = login(client, cloud)

    #: 响应里只有邮箱 —— **cookie 与令牌都不在任何字段名、任何值里**。
    assert response.json() == {"email": EMAIL}
    strings = _all_strings(response.json())
    assert not any(COOKIE_VALUE in one or DEVICE_TOKEN in one for one in strings), strings
    assert COOKIE_VALUE not in response.text and DEVICE_TOKEN not in response.text

    #: 换令牌与退会话都带着登录拿到的 cookie;设备名是本机主机名。
    _login, exchange, logout, _catalog = cloud.requests
    assert (exchange.method, exchange.url.path) == ("POST", "/device-tokens")
    assert exchange.headers.get("cookie") == f"{COOKIE_NAME}={COOKIE_VALUE}"
    assert json.loads(exchange.content)["name"] == cloud_binding.device_name()
    assert (logout.method, logout.url.path) == ("POST", "/logout")
    assert logout.headers.get("cookie") == f"{COOKIE_NAME}={COOKIE_VALUE}"
    #: 连响应头里也不许把它带回来(Cloud 的 Set-Cookie 只该落进本地那一行)。
    assert "set-cookie" not in response.headers
    assert COOKIE_VALUE not in str(dict(response.headers))

    #: 表里确实有一行,而且是**密文**。
    with SessionLocal() as db:
        from app.db.models import CloudLogin

        stored = db.query(CloudLogin).one()
        assert stored.email == EMAIL
        assert stored.device_token_id == DEVICE_TOKEN_ID
        assert stored.device_token == DEVICE_TOKEN
        assert DEVICE_TOKEN not in str(rows()), "令牌原文出现在盘上"
        assert COOKIE_VALUE not in str(rows()), "cookie 落了盘"


def test_a_login_that_cannot_get_a_device_token_stores_nothing(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"user": {"email": EMAIL}}, headers={"set-cookie": LOGIN_COOKIE})
    cloud.reply(500, {"error": "internal_error"})
    response = client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 502, response.text
    assert rows() == []


def test_phone_password_login_uses_the_same_device_token_path(cloud: FakeCloud) -> None:
    client = fresh_client()
    queue_successful_login(cloud, email="+8613800138000")
    response = client.post(
        "/api/cloud/v1/login/phone",
        json={"phone": "+8613800138000", "password": PASSWORD},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"email": "+8613800138000"}
    assert len(rows()) == 1
    assert PASSWORD not in str(rows())


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


# ---------------------------------------------------------------- ② 之后的读带上令牌


def test_logged_in_reads_carry_the_device_token(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)

    cloud.reply(200, {"user": {"email": EMAIL}})
    response = client.get("/api/cloud/v1/me")

    assert response.status_code == 200, response.text
    assert response.json() == {"email": EMAIL}
    outbound = cloud.requests[-1]
    assert outbound.headers.get("authorization") == BEARER
    assert "cookie" not in outbound.headers

    #: 同样的断言走一条**公开读**的分享详情:登录之后它自动以登录身份读。
    cloud.reply(200, {"id": "share-1", "title": "Space Opera"})
    assert client.get("/api/cloud/v1/shares/share-1").status_code == 200
    assert cloud.requests[-1].headers.get("authorization") == BEARER


def test_a_guest_read_does_not_invent_credentials(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"id": "share-1"})

    assert client.get("/api/cloud/v1/shares/share-1").status_code == 200
    assert "cookie" not in cloud.requests[-1].headers
    assert "authorization" not in cloud.requests[-1].headers


# ---------------------------------------------------------------- ③ 云端 401:清行 + 401


def test_a_cloud_401_clears_the_local_row_and_answers_401(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    assert rows()

    cloud.reply(401, {"error": "device_token_invalid", "message": {"en": "Sign in again.", "zh": "请重新登录。"}})
    response = client.get("/api/cloud/v1/me")

    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "not_authenticated"
    assert rows() == [], "云端说令牌已吊销,本地那一行还留着"


# ---------------------------------------------------------------- ④ 退出登录


def test_logout_revokes_the_device_token_and_deletes_the_row(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)

    cloud.reply_raw(httpx.Response(204))
    response = client.post("/api/cloud/v1/logout")

    assert response.status_code == 204, response.text
    assert rows() == []
    outbound = cloud.requests[-1]
    assert (outbound.method, outbound.url.path) == ("DELETE", "/device-tokens/current")
    assert outbound.headers.get("authorization") == BEARER


def test_logout_still_signs_out_locally_when_cloud_is_unreachable(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)

    cloud.fail(httpx.ConnectError("offline"))
    client.post("/api/cloud/v1/logout")

    assert rows() == []


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
    #: 登录这一跳本身(之后还有换令牌、退会话、问目录)。
    outbound = cloud.requests[0]

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
        ("post", "/api/cloud/v1/login/phone", {"phone": "+8613800138000", "password": PASSWORD}),
        ("post", "/api/cloud/v1/login/code/verify", {"email": EMAIL, "code": "123456"}),
        ("post", "/api/cloud/v1/login/sms/code", {"phone": "+8613800138000"}),
        ("post", "/api/cloud/v1/login/sms/verify", {"phone": "+8613800138000", "code": "123456"}),
        ("post", "/api/cloud/v1/me/password", {"current_password": PASSWORD, "new_password": "New-Horse-9"}),
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
    ("post", "/api/cloud/v1/login/sms/code", {"phone": "+8613800138000"}, "POST", "/login/sms/code"),
    ("post", "/api/cloud/v1/me/password", {"current_password": PASSWORD, "new_password": "New-Horse-9"}, "POST", "/me/password"),
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
    assert outbound.headers.get("authorization") == BEARER


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


def test_the_login_code_flow_stores_a_device_token_on_verify(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"sent": True})
    assert client.post("/api/cloud/v1/login/code", json={"email": EMAIL}).status_code == 200
    assert (cloud.requests[-1].method, cloud.requests[-1].url.path) == ("POST", "/login/code")

    queue_successful_login(cloud)
    response = client.post("/api/cloud/v1/login/code/verify", json={"email": EMAIL, "code": "123456"})

    assert response.status_code == 200, response.text
    assert response.json() == {"email": EMAIL}
    assert COOKIE_VALUE not in response.text
    assert len(rows()) == 1


def test_the_sms_login_flow_stores_a_device_token_on_verify(cloud: FakeCloud) -> None:
    client = fresh_client()
    cloud.reply(200, {"sent": True})
    assert client.post("/api/cloud/v1/login/sms/code", json={"phone": "+8613800138000"}).status_code == 200
    assert (cloud.requests[-1].method, cloud.requests[-1].url.path) == ("POST", "/login/sms/code")

    queue_successful_login(cloud)
    response = client.post(
        "/api/cloud/v1/login/sms/verify",
        json={"phone": "+8613800138000", "code": "123456"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"email": "+8613800138000"}
    assert COOKIE_VALUE not in response.text
    assert len(rows()) == 1


def test_desktop_password_change_is_proxied_and_reports_password_state(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    cloud.reply(200, {"user": {"email": EMAIL, "has_password": True}})

    response = client.post(
        "/api/cloud/v1/me/password",
        json={"current_password": PASSWORD, "new_password": "New-Horse-9"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"email": EMAIL, "has_password": True}
    assert cloud.requests[-1].url.path == "/me/password"


def test_me_without_a_stored_login_is_401_without_touching_cloud(cloud: FakeCloud) -> None:
    client = fresh_client()

    response = client.get("/api/cloud/v1/me")

    assert response.status_code == 401
    assert cloud.requests == []
    assert rows() == []


def test_a_cloud_address_the_outbound_guard_blocks_is_a_503_that_says_why(cloud: FakeCloud) -> None:
    """服务端部署把 Cloud 配成内网地址、又没放行:说清是哪个地址被拦,不是 500。"""
    from app.core.outbound_guard import OutboundBlocked

    client = fresh_client()
    cloud.fail(OutboundBlocked("outboundErr_privateConfigured", host="10.0.0.5", address="10.0.0.5",
                               reason="", entry="10.0.0.5"))
    response = client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "cloud_blocked"
    assert "10.0.0.5" in response.json()["detail"]["message"]
    assert rows() == []


# ---------------------------------------------------------------- 「Mosael Cloud」连接(ADR 0088)


def _cloud_connection_rows():
    with engine.begin() as connection:
        profiles = list(connection.execute(text(
            "SELECT id, name, vendor, base_url FROM provider_profiles WHERE vendor = 'mosael-cloud'"
        )))
        models = list(connection.execute(text(
            "SELECT model_id, display_name, source FROM provider_models WHERE provider_profile_id IN "
            "(SELECT id FROM provider_profiles WHERE vendor = 'mosael-cloud')"
        )))
        rules = list(connection.execute(text(
            "SELECT model, billing_unit, unit_amount_micros, currency, effective_to IS NULL FROM provider_pricing_rules "
            "WHERE source = 'mosael-cloud' ORDER BY model, billing_unit, effective_to IS NULL"
        )))
    return profiles, models, rules


def test_signing_in_builds_the_mosael_cloud_connection_from_the_gateway_catalog(cloud: FakeCloud) -> None:
    client = fresh_client()
    queue_successful_login(cloud, models=GATEWAY_MODELS)
    assert client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200

    catalog = cloud.requests[-1]
    assert (catalog.method, catalog.url.path) == ("GET", "/gateway/v1/models")
    assert catalog.headers.get("authorization") == BEARER

    profiles, models, rules = _cloud_connection_rows()
    #: 端点不存在连接上(跟着部署配置走);名字固定。
    assert [(name, vendor, base_url) for _, name, vendor, base_url in profiles] == [("Mosael Cloud", "mosael-cloud", "")]
    assert models == [("deepseek-chat", "DeepSeek V3", "mosael-cloud")]
    #: 0.002 积分 / token = 2000 积分 / 百万 token;币种是积分。
    assert rules == [
        ("deepseek-chat", "million_input_token", 2000 * 1_000_000, "CREDITS", 1),
        ("deepseek-chat", "million_output_token", 8000 * 1_000_000, "CREDITS", 1),
    ]


def test_the_connection_resolves_to_the_gateway_with_the_device_token_only_while_signed_in(cloud: FakeCloud) -> None:
    from app.db.models import ProviderProfile
    from app.domain.providers import credentials

    client = fresh_client()
    login(client, cloud)
    with SessionLocal() as db:
        profile = db.query(ProviderProfile).filter_by(vendor="mosael-cloud").one()
        resolved = credentials.resolve_connection(db, profile, profile.owner_user_id)
        assert resolved is not None
        assert resolved.base_url == f"{CLOUD_URL}/gateway/v1"
        assert resolved.api_key == DEVICE_TOKEN
        profile_id, owner = profile.id, profile.owner_user_id

    cloud.reply_raw(httpx.Response(204))
    client.post("/api/cloud/v1/logout")
    with SessionLocal() as db:
        profile = db.get(ProviderProfile, profile_id)
        #: 登出不删连接(默认模型、画板还指着它),只是解析不出钥匙了。
        assert profile is not None
        assert credentials.resolve_connection(db, profile, owner) is None


def test_refresh_moves_a_changed_price_forward_and_drops_delisted_models(cloud: FakeCloud) -> None:
    client = fresh_client()
    queue_successful_login(cloud, models=GATEWAY_MODELS)
    client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": PASSWORD})

    cloud.reply(200, {"object": "list", "data": [
        {"id": "kimi-k2", "object": "model", "name": "Kimi K2",
         "pricing": {"prompt": "0.001", "completion": "0.008", "currency": "CREDITS"}},
    ]})
    response = client.post("/api/cloud/v1/connection/sync")
    assert response.status_code == 200, response.text
    assert response.json()["models"] == 1

    _profiles, models, rules = _cloud_connection_rows()
    assert [one[0] for one in models] == ["kimi-k2"]
    #: 下架的 deepseek-chat:规则截止(不删,过去的账还能对回去);kimi-k2 的规则从此刻起生效。
    assert ("deepseek-chat", "million_input_token", 2000 * 1_000_000, "CREDITS", 0) in rules
    assert ("kimi-k2", "million_input_token", 1000 * 1_000_000, "CREDITS", 1) in rules


def test_a_revoked_token_on_refresh_signs_the_user_out(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    cloud.reply(401, {"error": "device_token_invalid", "message": {"en": "x", "zh": "x"}})
    assert client.post("/api/cloud/v1/connection/sync").status_code == 401
    assert rows() == []


def test_signing_in_still_works_when_the_gateway_is_not_there(cloud: FakeCloud) -> None:
    """这个部署的 Cloud 还没有网关(404)、或网关一时不可用:登录照样成功,连接之后再刷新。"""
    client = fresh_client()
    cloud.reply(200, {"user": {"email": EMAIL}}, headers={"set-cookie": LOGIN_COOKIE})
    cloud.reply(201, {"token": {"id": DEVICE_TOKEN_ID, "name": "host"}, "secret": DEVICE_TOKEN})
    cloud.reply_raw(httpx.Response(204))
    cloud.reply(404, {"error": "not_found"})
    response = client.post("/api/cloud/v1/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert rows()


def test_gateway_account_is_relayed_with_the_device_token(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)
    cloud.reply(200, {"credits": 998, "batches": [], "next_grant_at": None, "plan": "Pro"})
    response = client.get("/api/cloud/v1/gateway/account")
    assert response.status_code == 200, response.text
    assert response.json()["credits"] == 998
    assert cloud.requests[-1].url.path == "/gateway/account"
    assert cloud.requests[-1].headers.get("authorization") == BEARER


def test_the_connection_counts_as_usable_exactly_while_signed_in(cloud: FakeCloud) -> None:
    """连接列表上的 `is_mine`(界面据此判「能不能用」)和 resolve_connection 同一个判据:登着就算有钥匙。"""
    client = fresh_client()
    login(client, cloud)

    def cloud_row() -> dict:
        return next(one for one in client.get("/api/settings/providers").json() if one["vendor"] == "mosael-cloud")

    assert cloud_row()["is_mine"] is True
    cloud.reply_raw(httpx.Response(204))
    client.post("/api/cloud/v1/logout")
    assert cloud_row()["is_mine"] is False


# ---------------------------------------------------------------- 在线购买(ADR 0088 第 3 步)


def test_plans_orders_and_order_status_are_relayed_with_the_device_token(cloud: FakeCloud) -> None:
    client = fresh_client()
    login(client, cloud)

    cloud.reply(200, {"plans": [{"slug": "pro", "price_cents": 2900}], "channels": ["alipay"]})
    assert client.get("/api/cloud/v1/plans").json()["channels"] == ["alipay"]
    assert cloud.requests[-1].url.path == "/plans"

    cloud.reply(201, {"order": {"id": "o1", "status": "pending", "code_url": "https://qr.alipay.com/x"}})
    response = client.post("/api/cloud/v1/orders", json={"plan": "pro", "channel": "alipay"})
    assert response.status_code == 201, response.text
    sent = cloud.requests[-1]
    assert (sent.method, sent.url.path) == ("POST", "/orders")
    assert json.loads(sent.content) == {"plan": "pro", "channel": "alipay"}
    assert sent.headers.get("authorization") == BEARER

    cloud.reply(200, {"order": {"id": "o1", "status": "paid"}})
    assert client.get("/api/cloud/v1/orders/o1").json()["order"]["status"] == "paid"
    assert cloud.requests[-1].url.path == "/orders/o1"


def test_ordering_without_signing_in_is_401_without_touching_cloud(cloud: FakeCloud) -> None:
    client = fresh_client()
    assert client.post("/api/cloud/v1/orders", json={"plan": "pro", "channel": "alipay"}).status_code == 401
    assert client.post("/api/cloud/v1/orders", json={"plan": "pro", "channel": "paypal"}).status_code == 422
    assert cloud.requests == []
