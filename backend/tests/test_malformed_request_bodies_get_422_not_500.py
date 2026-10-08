"""请求体和 Content-Type 对不上(text/plain 里装着一段 JSON)时回 422,不是 500(SEC-5)。

校验失败的 422 由 main._invalid_request 自己渲染,把出错的原值回显进错误体。请求体不是 JSON 对象时那个原值是原始的
bytes,编不进 JSON:编码器抛异常、客户端收到 500 —— 「因为拒绝得对而崩掉」,而且不用登录就打得到(注册接口)。
"""

from __future__ import annotations

from tests.util import fresh_client


def test_注册接口收到_text_plain_的正文_回422并说清是哪儿不对() -> None:
    client = fresh_client()
    client.headers.pop("Authorization", None)

    response = client.post(
        "/api/auth/register", content=b'{"username":"x","password":"y"}', headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail
    assert '"username"' in str(detail[0].get("input")), "原值解成文字回显,看得出收到了什么"


def test_回显的原始正文截短() -> None:
    client = fresh_client()
    response = client.post("/api/auth/register", content=b"\xff" * 5000, headers={"Content-Type": "text/plain"})
    assert response.status_code == 422
    assert len(str(response.json()["detail"][0].get("input"))) <= 400


def test_NaN_照旧回显成字面() -> None:
    client = fresh_client()
    response = client.post("/api/workspaces", content=b'{"name": NaN}', headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
