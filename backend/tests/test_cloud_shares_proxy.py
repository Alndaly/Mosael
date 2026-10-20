"""社区分享的**只读**反代:桌面端打本机后端,本机后端替它去 Cloud 取。

Cloud 只接受官网同源、不开 CORS,所以真机上的社区分享要经本地后端转发(否则永远打不开,
界面还会把一次"没接上"说成"分享不存在")。这三条路由只做读:详情、内容、下载(+1 计数)。
**写接口(发布 / 评论 / 点赞)不转发**:它们要第一方会话,桌面端没有。

不碰网络:Cloud 那一侧按 `get_json` / `post_json` 打桩,方法那一层按 `RetryingClient` 打桩。
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest

from app.core.config import settings
from app.domain import cloud_binding
from tests.util import fresh_client

CLOUD_URL = "https://cloud.example/api/cloud/v1"
SHARE_ID = "0123456789abcdef0123456789abcdef"

#: 刻意带上本地后端不认识、也不该丢的字段:反代是逐字段转发,不是重拼一个"像样"的对象。
DETAIL = {
    "id": SHARE_ID,
    "kind": "workflow",
    "title": "Space Opera",
    "summary": "一镜到底的预告片",
    "bytes": 4212,
    "license": "CC-BY-4.0",
    "created_at": "2026-10-20T12:00:00Z",
    "author": {"display_name": "Alice", "handle": "alice", "avatar_seed": "seed-1"},
    "stats": {"downloads": 3, "likes": 2, "favorites": 1, "comments": 4},
    "liked_by_me": False,
    "favorited_by_me": True,
    "server_time": "2026-10-20T12:00:01Z",
    "unknown_future_field": {"nested": [1, 2, 3]},
}
PAYLOAD = {"version": 1, "nodes": [{"id": "n1", "type": "start"}], "edges": []}


class FakeCloud:
    """按顺序回放 `(status, body)` / 异常,并记下每一次调用的方法和路径。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, path: str):
        self.calls.append(("GET", path, {}))
        return self._next()

    def post(self, path: str, payload: dict):
        self.calls.append(("POST", path, payload))
        return self._next()

    def _next(self):
        found = self.responses.pop(0)
        if isinstance(found, BaseException):
            raise found
        return found


def stub_cloud(monkeypatch, responses) -> FakeCloud:
    """把 Cloud 那一跳换掉,但保留「路由 → get_json / post_json」这一段真代码。"""
    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL)
    fake = FakeCloud(responses)
    monkeypatch.setattr(cloud_binding, "get_json", fake.get)
    monkeypatch.setattr(cloud_binding, "post_json", fake.post)
    return fake


class FakeResponse:
    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def stub_client(monkeypatch, response: FakeResponse) -> list[tuple[str, str, dict]]:
    """把 `RetryingClient` 换成记录器 —— 这样断言的是**真正发出去的那一次**(含 method / URL / kwargs)。"""
    calls: list[tuple[str, str, dict]] = []

    class Recording:
        def __init__(self, *args, **kwargs) -> None:
            self.options = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            return response

        def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return response

    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL)
    monkeypatch.setattr(cloud_binding, "RetryingClient", Recording)
    return calls


# ---------------------------------------------------------------- ① 三条路由通,响应逐字段一致


def test_share_detail_is_relayed_field_for_field(monkeypatch):
    client = fresh_client()
    fake = stub_cloud(monkeypatch, [(200, DETAIL)])

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}")

    assert response.status_code == 200, response.text
    assert response.json() == DETAIL
    assert fake.calls == [("GET", f"/shares/{SHARE_ID}", {})]


def test_share_payload_is_relayed_without_reshaping(monkeypatch):
    client = fresh_client()
    fake = stub_cloud(monkeypatch, [(200, {"payload": PAYLOAD})])

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}/payload")

    assert response.status_code == 200, response.text
    assert response.json() == {"payload": PAYLOAD}
    assert fake.calls == [("GET", f"/shares/{SHARE_ID}/payload", {})]


def test_get_json_uses_the_configured_cloud_url(monkeypatch):
    """`get_json` 和 `post_json` 共用 `cloud_url`(含去掉尾斜杠)和同一个客户端。"""
    calls = stub_client(monkeypatch, FakeResponse(200, DETAIL))
    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL + "/")

    status, body = cloud_binding.get_json(f"/shares/{SHARE_ID}")

    assert (status, body) == (200, DETAIL)
    assert calls == [("GET", f"{CLOUD_URL}/shares/{SHARE_ID}", {})]


def test_get_json_keeps_a_list_body(monkeypatch):
    body = [{"id": SHARE_ID}]
    stub_client(monkeypatch, FakeResponse(200, body))

    assert cloud_binding.get_json("/shares") == (200, body)


# ---------------------------------------------------------------- ② 状态码映射


@pytest.mark.parametrize("status", [404, 413, 422])
def test_remote_4xx_statuses_pass_through_untouched(monkeypatch, status):
    """404 / 413 / 422 原样交出去:后端不替界面把 404 翻译成"分享不存在"。"""
    client = fresh_client()
    remote = {"error": "some_cloud_error", "message": {"en": "nope", "zh": "不行"}}
    stub_cloud(monkeypatch, [(status, remote)])

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}")

    assert response.status_code == status
    assert response.json() == remote


def test_a_remote_5xx_is_502(monkeypatch):
    client = fresh_client()
    stub_cloud(monkeypatch, [(503, {"error": "temporarily_unavailable", "message": {"en": "later", "zh": "稍后"}})])

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "cloud_upstream_error"
    assert response.json()["detail"]["upstream_status"] == 503


def test_a_slow_cloud_is_504_not_a_hung_request(monkeypatch):
    """远端慢 → 504 + 人话;不让界面等满客户端超时。"""

    calls: list[str] = []

    class Slow:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

        def get(self, url, **kwargs):
            calls.append(url)
            raise httpx.ReadTimeout("too slow", request=httpx.Request("GET", url))

    client = fresh_client()
    monkeypatch.setattr(settings, "cloud_url", CLOUD_URL)
    monkeypatch.setattr(cloud_binding, "RetryingClient", Slow)

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}")

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "cloud_timeout"
    assert calls == [f"{CLOUD_URL}/shares/{SHARE_ID}"]


def test_an_unreachable_cloud_is_503(monkeypatch):
    client = fresh_client()
    stub_cloud(monkeypatch, [cloud_binding.CloudUnavailable("connection refused")])

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "cloud_unreachable"


# ---------------------------------------------------------------- ③ 没配 Cloud


def test_without_cloud_url_every_share_route_says_not_configured(monkeypatch):
    """同一个部署没接 Cloud,不管点哪条路都是这句话。"""
    client = fresh_client()
    monkeypatch.setattr(settings, "cloud_url", "")

    expected: str | None = None
    for method, path in (
        ("get", f"/api/cloud/v1/shares/{SHARE_ID}"),
        ("get", f"/api/cloud/v1/shares/{SHARE_ID}/payload"),
        ("post", f"/api/cloud/v1/shares/{SHARE_ID}/download"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 503, (method, path, response.text)
        assert response.json()["detail"]["code"] == "cloud_not_configured"
        expected = expected or response.json()["detail"]["message"]
        assert response.json()["detail"]["message"] == expected


# ---------------------------------------------------------------- ④ id 是外部输入


@pytest.mark.parametrize("bad_id", ["bad.id", "a" * 65, "share id", "share+id"])
def test_a_malformed_share_id_is_422_and_never_reaches_cloud(monkeypatch, bad_id):
    """422(不是 404):形状在**拼 URL 之前**就被拒了,所以那一段永远进不了云地址。"""
    client = fresh_client()
    fake = stub_cloud(monkeypatch, [])

    response = client.get(f"/api/cloud/v1/shares/{quote(bad_id, safe='')}")

    assert response.status_code == 422, response.text
    assert fake.calls == []


def test_the_longest_allowed_id_is_still_forwarded(monkeypatch):
    longest = "a" * 64
    client = fresh_client()
    fake = stub_cloud(monkeypatch, [(200, DETAIL)])

    response = client.get(f"/api/cloud/v1/shares/{longest}")

    assert response.status_code == 200, response.text
    assert fake.calls == [("GET", f"/shares/{longest}", {})]


# ---------------------------------------------------------------- ⑤ download 是 POST


def test_download_forwards_a_post(monkeypatch):
    """Cloud 那条会 +1 计数:这里必须是 POST,不能"顺手"改成 GET。"""
    client = fresh_client()
    calls = stub_client(monkeypatch, FakeResponse(200, {"payload": PAYLOAD}))

    response = client.post(f"/api/cloud/v1/shares/{SHARE_ID}/download")

    assert response.status_code == 200, response.text
    assert response.json() == {"payload": PAYLOAD}
    assert [method for method, _, _ in calls] == ["POST"]
    assert calls[0][1] == f"{CLOUD_URL}/shares/{SHARE_ID}/download"


def test_a_get_on_download_is_not_accepted(monkeypatch):
    """GET 不能顶替 POST:本地这一层就该是 405,不能转发出去。"""
    client = fresh_client()
    fake = stub_cloud(monkeypatch, [])

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}/download")

    assert response.status_code == 405
    assert fake.calls == []


# ---------------------------------------------------------------- 安全 / 范围


def test_the_local_session_is_not_forwarded_to_cloud(monkeypatch):
    """本地登录态、设备凭据都不出这台机器;Cloud 那侧按游客认。"""
    client = fresh_client()
    #: 进来这一跳确实带着本地会话(测试客户端登录时就挂了 Bearer),而出去那一跳一个头都不带。
    client.cookies.set("mosael", "local-session")
    assert client.headers["Authorization"].startswith("Bearer ")
    calls = stub_client(monkeypatch, FakeResponse(200, DETAIL))

    response = client.get(f"/api/cloud/v1/shares/{SHARE_ID}")

    assert response.status_code == 200, response.text
    _method, _url, kwargs = calls[0]
    assert kwargs == {}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/cloud/v1/shares"),
        ("post", f"/api/cloud/v1/shares/{SHARE_ID}/like"),
        ("post", f"/api/cloud/v1/shares/{SHARE_ID}/favorite"),
        ("post", f"/api/cloud/v1/shares/{SHARE_ID}/comments"),
        ("delete", f"/api/cloud/v1/shares/{SHARE_ID}"),
    ],
)
def test_write_and_list_paths_are_not_proxied(monkeypatch, method, path):
    """只开三个读接口:转写接口过去只会 401(它们要第一方会话),那是下一笔的事。"""
    client = fresh_client()
    fake = stub_cloud(monkeypatch, [])

    response = getattr(client, method)(path)

    assert response.status_code in {404, 405}, (method, path, response.text)
    assert fake.calls == []
