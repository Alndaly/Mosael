"""本机桌面后端对网页的暴露面。

- CORS 名单里的 `null` 只给打包版界面(file://);任何网页里的 sandboxed iframe 也是 `null`。桌面版要求 null 来源
  带主密钥派生的壳令牌(core/shell_origin),Electron 主进程替自己的请求加上,网页算不出。
- Host 头只认本机的名字(桌面版)或部署者配的(MOSAEL_ALLOWED_HOSTS),挡 DNS rebinding。
- 团队服务器不配就不检查,行为不变。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import allowed_hosts, settings
from app.core.shell_origin import shell_token


@pytest.fixture()
def desktop(monkeypatch):
    from app.main import create_app
    from tests.util import fresh_client

    fresh_client()  # 建好库
    monkeypatch.setattr(settings, "local_desktop", True)
    monkeypatch.setattr(settings, "allowed_hosts", "")

    return TestClient(create_app(), base_url="http://127.0.0.1:8800")


def test_桌面版_null_来源没带壳令牌_一律拒_连预检也拒(desktop) -> None:
    assert desktop.get("/api/auth/bootstrap", headers={"Origin": "null"}).status_code == 403
    preflight = desktop.options("/api/auth/register", headers={
        "Origin": "null", "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 403
    assert desktop.get("/api/auth/bootstrap", headers={"Origin": "null", "X-Mosael-Shell": "guess"}).status_code == 403


def test_桌面版_带对壳令牌的_null_来源照常放行_还能读回响应(desktop) -> None:
    res = desktop.get("/api/auth/bootstrap", headers={"Origin": "null", "X-Mosael-Shell": shell_token()})
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "null"


def test_桌面版_没有_Origin_的请求不受影响(desktop) -> None:
    """<img src=…?token=> 这类不走 CORS 的请求没有 Origin,本来就要带令牌。"""
    assert desktop.get("/api/auth/bootstrap").status_code == 200


def test_桌面版_Host_只认本机的名字(desktop) -> None:
    assert desktop.get("/api/auth/bootstrap", headers={"Host": "localhost:8800"}).status_code == 200
    assert desktop.get("/api/auth/bootstrap", headers={"Host": "attacker.example:8800"}).status_code == 400


def test_Host_白名单_配了用配的_服务端没配就不检查(monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", False)
    monkeypatch.setattr(settings, "allowed_hosts", "")
    assert allowed_hosts() == []
    monkeypatch.setattr(settings, "allowed_hosts", "mosael.team.example, 10.0.0.5")
    assert allowed_hosts() == ["mosael.team.example", "10.0.0.5"]
    monkeypatch.setattr(settings, "allowed_hosts", "")
    monkeypatch.setattr(settings, "local_desktop", True)
    assert allowed_hosts() == ["127.0.0.1", "localhost"]


def test_壳令牌和_Electron_同一个算法() -> None:
    """electron/master-key.cjs 的 shellToken:HMAC-SHA256(主密钥, "mosael-shell-origin") 的十六进制。"""
    import hashlib
    import hmac

    from app.core.secrets_at_rest import master_key

    assert shell_token() == hmac.new(master_key(), b"mosael-shell-origin", hashlib.sha256).hexdigest()


#: 和 electron/master-key.test.ts 里那一条是同一个数:两边对同一把钥匙算出同一个壳令牌。
KNOWN_SHELL_TOKEN = "0a309c0628230652b8d072869e0206b5895ccbe6683c9a1e5ea9908583c9a6fb"


def test_壳令牌的已知值和_Electron_那边对得上(monkeypatch) -> None:
    from app.core import secrets_at_rest

    monkeypatch.setattr(secrets_at_rest, "master_key", lambda: b"test-master-key")
    assert shell_token() == KNOWN_SHELL_TOKEN

