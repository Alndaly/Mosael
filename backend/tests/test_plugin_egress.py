"""插件连接往外连走哪条路:默认跟随 Mosael 的出站代理,连接自己可以覆盖(见 domain/plugins/egress)。

此前全局代理根本到不了插件:子进程只拿到 PATH/HOME/LANG,于是设置页说「插件也走这个代理」是假话,
MinerU 只好在自己的清单里另发明一套网络设置。这里钉住三件事:
- **决定只有一处**,优先级是「连接的覆盖 > 全局」,三种情形各自给出什么;
- 两种子进程(进程插件、stdio MCP)拿到的是同一份,后端替连接发的 HTTP 请求照同一个决定走;
- 接口能改、改错了当场说。
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginInstance
from app.domain import network
from app.domain.plugins import egress as plugin_egress
from app.domain.plugins.egress import Egress
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.mcp_bridge import stdio_env
from tests.test_plugins import SIMPLE, install

PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _global(proxy_url: str, no_proxy: str = "") -> None:
    """改全局出站代理那一行。直接写库,不走设置接口 —— 那条会顺手改本进程的环境变量,污染同一进程里后跑的用例。"""
    with SessionLocal() as db:
        row = network.get_config(db)
        row.proxy_url, row.no_proxy = proxy_url, no_proxy
        db.commit()


def _connected():
    """装一个会把自己的环境原样交回来的插件,启用它。返回 (client, 连接 id)。"""
    client = install(SIMPLE)
    instance_id = client.get("/api/plugins").json()[0]["instances"][0]["id"]
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
    return client, instance_id


def _child_env(client, instance_id: str) -> dict[str, str]:
    out = client.post(f"/api/plugins/instances/{instance_id}/tools/shout/invoke", json={"input": {"text": "x"}}).json()
    assert out["status"] == "succeeded", out
    return out["output"]["env"]


def _proxy_part(env: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in env.items() if key.upper() in PROXY_KEYS}


class Test三种情形:
    def test_跟随_全局配了代理_插件拿到的就是那一份_连同绕过列表(self) -> None:
        client, instance_id = _connected()
        _global("http://global:7890", "api.moonshot.cn")
        env = _child_env(client, instance_id)
        assert env["HTTPS_PROXY"] == env["https_proxy"] == "http://global:7890"
        bypass = env["NO_PROXY"].split(",")
        assert "api.moonshot.cn" in bypass and "127.0.0.1" in bypass

    def test_跟随_全局没配_什么都不给_和后端自己的出站一样(self) -> None:
        client, instance_id = _connected()
        _global("")
        assert _proxy_part(_child_env(client, instance_id)) == {}

    def test_连接自己的代理盖过全局_绕过列表只剩回环(self) -> None:
        """全局那份绕过列表是替全局代理调的(国内端点别走境外代理);覆盖的意思是这个连接整个走这一条。"""
        client, instance_id = _connected()
        _global("http://global:7890", "api.moonshot.cn")
        saved = client.patch(
            f"/api/plugins/instances/{instance_id}",
            json={"network": {"mode": "proxy", "proxy_url": "http://mainland:8080"}},
        ).json()
        assert saved["network"] == {"mode": "proxy", "proxy_url": "http://mainland:8080"}
        env = _child_env(client, instance_id)
        assert env["HTTPS_PROXY"] == env["https_proxy"] == "http://mainland:8080"
        assert env["NO_PROXY"].split(",") == list(network.LOOPBACK_NO_PROXY)

    def test_直连_明说谁都绕过_全局配了也不走(self) -> None:
        """只是不给代理变量不够:urllib / httpx 会退到系统代理。直连得说出来。"""
        client, instance_id = _connected()
        _global("http://global:7890")
        client.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "direct"}})
        assert _proxy_part(_child_env(client, instance_id)) == {"NO_PROXY": "*", "no_proxy": "*"}

    def test_换回跟随_代理地址不留一份看不见的旧值(self) -> None:
        client, instance_id = _connected()
        client.patch(
            f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "proxy", "proxy_url": "http://a:1"}}
        )
        back = client.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "follow"}}).json()
        assert back["network"] == {"mode": "follow", "proxy_url": ""}


class Test改错了当场说:
    @pytest.mark.parametrize("url", ["", "127.0.0.1:7890", "ftp://h:1", "http://"])
    def test_代理地址要写全(self, url: str) -> None:
        client, instance_id = _connected()
        res = client.patch(
            f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "proxy", "proxy_url": url}}
        )
        assert res.status_code == 422 and "代理地址" in res.json()["detail"]
        with SessionLocal() as db:
            assert db.get(PluginInstance, instance_id).network_mode == "follow", "报错了还是存进去了"

    def test_不认识的模式进不了门(self) -> None:
        client, instance_id = _connected()
        res = client.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "system"}})
        assert res.status_code == 422

    def test_领域层自己也挡(self) -> None:
        """接口有 Literal 挡着,但领域函数还有别的调用方(迁移之后的脚本、智能体)。"""
        with pytest.raises(PluginDomainError):
            plugin_egress.normalize("system", "")
        assert plugin_egress.normalize("direct", "http://leftover:1") == ("direct", "")
        assert plugin_egress.normalize("proxy", " socks5://127.0.0.1:1080 ") == ("proxy", "socks5://127.0.0.1:1080")


class Test两种子进程同一份_后端的请求同一个决定:
    def test_stdio_MCP_的环境里也有_宿主的排在插件配置之后(self) -> None:
        egress = Egress("http://p:1", "localhost")
        env = stdio_env({"HTTPS_PROXY": "插件自己写的"}, egress)
        assert env["HTTPS_PROXY"] == "http://p:1", "插件的配置盖掉了宿主替这个连接定的路"
        assert env["NODE_USE_ENV_PROXY"] == "1", "Node 写的 MCP 服务不看到它就不认代理变量"
        assert "HTTPS_PROXY" not in stdio_env({}, Egress())

    def test_后端替连接发的请求_代理_绕过_直连_跟随(self) -> None:
        proxied = Egress("http://p:1", network.effective_no_proxy(""))
        assert proxied.httpx_options("https://mcp.example/mcp") == {"trust_env": False, "proxy": "http://p:1"}
        assert proxied.httpx_options("http://127.0.0.1:3000/mcp") == {"trust_env": False}
        assert Egress(no_proxy="*").httpx_options("https://mcp.example/mcp") == {"trust_env": False}
        #: 什么都不说:照后端自己的出站(httpx 读本进程的环境,那份由全局设置写进去)。
        assert Egress().httpx_options("https://mcp.example/mcp") == {}

    def test_远程_HTTP_的_MCP_连接真的用上了这个决定(self, monkeypatch) -> None:
        import httpx2
        import mcp.client.streamable_http as streamable

        from app.domain.plugins import mcp_bridge

        seen: dict = {}

        class FakeClient:
            def __init__(self, **kwargs):
                seen.update(kwargs)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        class Stop(Exception):
            pass

        def refuse(*_args, **_kwargs):
            raise Stop

        monkeypatch.setattr(httpx2, "AsyncClient", FakeClient)
        monkeypatch.setattr(streamable, "streamable_http_client", refuse)
        manifest = {"kind": "mcp", "mcp": {"transport": "http", "url": "https://mcp.example/mcp"}}

        async def never(_session):
            raise AssertionError("不该连上")

        with pytest.raises(Stop):
            asyncio.run(mcp_bridge._run(manifest, {}, never, Egress("http://p:1", "localhost")))
        assert seen["proxy"] == "http://p:1" and seen["trust_env"] is False
