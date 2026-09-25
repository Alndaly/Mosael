"""插件连接不要连接上的钥匙 —— 但它仍然是**他的**连接(ADR 0020)。

整条钥匙链的判据是「有没有一份带秘密的凭据」:没有就解析不出连接,调用方报「请先配置」。
这条判据对插件连接永远为假:它的凭据在插件实例上,由插件运行时只注入给那个插件自己,连接上
根本没有钥匙可配。此前靠 vendor 预设上的 `keyless` 豁免(只有本机 ComfyUI 一家用);ComfyUI 搬成
插件之后,豁免变成一条结构事实:**`plugin_instance_id` 有值的连接不收钥匙**。

豁免只豁免钥匙,不豁免归属。
"""

from __future__ import annotations

import socket

from app.core.db import SessionLocal
from app.db.models import ProviderProfile, User
from app.domain import provider_credentials
from tests.util import fresh_client, second_client

PACKAGE = "dev.mosael.comfyui"


def _unused_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _plugin_connection(client) -> str:
    """接一个 ComfyUI(地址指向一个没人听的端口:目录刷不出来,但连接照样在)。返回连接 id。"""
    created = client.post(f"/api/plugins/{PACKAGE}/instances",
                          json={"config": {"server_url": f"http://127.0.0.1:{_unused_port()}"}}).json()
    client.patch(f"/api/plugins/instances/{created['id']}/permissions", json={"grants": {"network:comfyui": True}})
    client.patch(f"/api/plugins/instances/{created['id']}", json={"enabled": True})
    with SessionLocal() as db:
        return db.query(ProviderProfile).filter(ProviderProfile.plugin_instance_id == created["id"]).one().id


def _user(name: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == name).one().id


def test_插件连接没有钥匙也解析得出来() -> None:
    client = fresh_client()
    profile_id = _plugin_connection(client)
    with SessionLocal() as db:
        resolved = provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), _user("tester"))
    assert resolved is not None, "插件连接被当成「没配钥匙」挡下了"
    assert resolved.api_key == "" and resolved.vendor == f"plugin:{PACKAGE}"


def test_普通连接照旧要钥匙() -> None:
    """这不是把闸放开:要钥匙的照旧要,没有就解析不出来。"""
    client = fresh_client()
    created = client.post("/api/settings/providers", json={
        "name": "某端点", "vendor": "openai-compatible",
        "config": {"base_url": "https://x.example/v1", "default_model": "m", "api_key": "k"},
    }).json()
    client.delete(f"/api/settings/providers/{created['id']}/credential")
    with SessionLocal() as db:
        assert provider_credentials.resolve_connection(db, db.get(ProviderProfile, created["id"]), _user("tester")) is None


def test_别人的插件连接仍然不是我的() -> None:
    client = fresh_client()
    profile_id = _plugin_connection(client)
    mate = second_client("mate")
    assert all(row["id"] != profile_id for row in mate.get("/api/settings/providers").json())
    assert mate.get(f"/api/settings/providers/{profile_id}/models").status_code == 404
    with SessionLocal() as db:
        assert provider_credentials.resolve_connection(db, db.get(ProviderProfile, profile_id), _user("mate")) is None
