"""宿主替插件交出去的东西照契约收口(PLG-15):注入进程的凭据只按清单现在声明的、换令牌照这个连接的出站走、MCP 服务给的
工具清单照运行时报的工具同一条规矩收。

- 插件更新后去掉的凭据键,那一行还在库里:插件页照清单列凭据,看不到它、也删不掉;此前它照样每次注入插件进程。
- 换令牌此前走后端默认的出口:连接设成直连、走它自己的代理时,插件自己的调用通、授权这一步不通。
- MCP 清单此前照单全收:名字带点的,工作流节点类型 `plugin.<包>.<a.b>` 被切错、智能体工具名也不收点;重名的只调得到一个。
"""

from __future__ import annotations

import json
from typing import Any

from app.core.db import SessionLocal
from app.domain.plugins import install as installer
from tests.test_plugins import install, plugins_root

TOKENED = {
    "id": "dev.tokened",
    "name": "带令牌的服务",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "instance": {
        "credentials": [
            {"key": "app_key", "label": "AppKey"},
            {"key": "refresh_token", "label": "Refresh Token"},
            {"key": "old_token", "label": "旧版本的令牌"},
        ],
        "oauth": {
            "authorize_url": "https://open.example/authorize",
            "token_url": "https://open.example/token",
            "client_id_field": "app_key",
            "stores": {"refresh_token": "refresh_token"},
        },
    },
    "tools": {
        "expose": "all",
        "declare": [{"name": "shout", "description": "大写。", "read_only": True,
                     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}}}],
    },
}


def _enabled(client) -> str:
    created = client.post(f"/api/plugins/{TOKENED['id']}/instances", json={"config": {}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
    return instance_id


def _child_env(client, instance_id: str) -> dict[str, str]:
    out = client.post(f"/api/plugins/instances/{instance_id}/tools/shout/invoke", json={"input": {"text": "x"}}).json()
    assert out.get("status") == "succeeded", out
    return out["output"]["env"]


def test_插件更新后去掉的凭据键_不再注入插件进程() -> None:
    client = install(TOKENED)
    instance_id = _enabled(client)
    saved = client.patch(f"/api/plugins/instances/{instance_id}/credentials",
                         json={"values": {"app_key": "k1", "refresh_token": "rt-0", "old_token": "leftover"}})
    assert saved.status_code == 200, saved.text
    assert _child_env(client, instance_id)["OLD_TOKEN"] == "leftover", "声明着的时候照常注入"

    newer = {**TOKENED, "version": "1.1.0",
             "instance": {**TOKENED["instance"], "credentials": TOKENED["instance"]["credentials"][:2]}}
    (plugins_root() / "tokened" / "mosael.plugin.json").write_text(json.dumps(newer), encoding="utf-8")
    with SessionLocal() as db:
        installer.sync(db, plugins_root())
    shown = [one["key"] for one in client.get(f"/api/plugins/instances/{instance_id}/credentials").json()]
    assert shown == ["app_key", "refresh_token"], "插件页上已经看不到它了"
    env = _child_env(client, instance_id)
    assert "OLD_TOKEN" not in env, "看不到、删不掉的那一格,不再每次交给插件"
    assert env["APP_KEY"] == "k1"


def test_换令牌照这个连接的出站走(monkeypatch) -> None:
    from app.domain.plugins import oauth as plugin_oauth

    seen: dict[str, Any] = {}

    class Answer:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"refresh_token": "rt-1"}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            seen["client"] = kwargs

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

        def post(self, url: str, data: dict[str, Any]) -> Answer:
            seen["url"] = url
            return Answer()

    monkeypatch.setattr(plugin_oauth, "RetryingClient", FakeClient)
    client = install(TOKENED)
    instance_id = _enabled(client)
    client.patch(f"/api/plugins/instances/{instance_id}/credentials", json={"values": {"app_key": "k1"}})
    client.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "proxy", "proxy_url": "http://mainland:8080"}})
    done = client.post(f"/api/plugins/instances/{instance_id}/oauth", json={"code": "c-1"})
    assert done.status_code == 200, done.text
    assert seen["url"] == "https://open.example/token"
    assert seen["client"]["proxy"] == "http://mainland:8080" and seen["client"]["trust_env"] is False, \
        "连接走它自己的代理:换令牌这一下也走那条"

    client.patch(f"/api/plugins/instances/{instance_id}", json={"network": {"mode": "direct"}})
    assert client.post(f"/api/plugins/instances/{instance_id}/oauth", json={"code": "c-2"}).status_code == 200
    assert seen["client"]["trust_env"] is False and "proxy" not in seen["client"], "直连:不走后端的全局代理"
    refresh = next(one for one in client.get(f"/api/plugins/instances/{instance_id}/credentials").json()
                   if one["key"] == "refresh_token")
    assert refresh["filled"] is True


def test_MCP_服务给的工具清单_名字不合规矩的_重名的不收(monkeypatch) -> None:
    from app.domain.plugins import tools as tools_domain

    mcp = {"id": "dev.mcpnames", "name": "MCP 名字", "version": "1.0.0", "runtime": {"kind": "mcp", "command": "x"}}
    reported = [
        {"name": "fetch_video", "description": "取一条", "input_schema": {"type": "object", "properties": {}}},
        {"name": "files.read", "description": "名字带点", "input_schema": {"type": "object", "properties": {}}},
        {"name": "fetch_video", "description": "又报了一个同名的", "input_schema": {"type": "object", "properties": {}}},
        {"name": "9lives", "description": "数字开头", "input_schema": {"type": "object", "properties": {}}},
        {"name": "search-posts", "description": "带连字符可以", "input_schema": {"type": "object", "properties": {}}},
    ]
    monkeypatch.setattr(tools_domain, "discover_tools", lambda *_args, **_kwargs: reported)
    client = install(mcp)
    instance_id = client.get("/api/plugins").json()[0]["instances"][0]["id"]
    enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).json()
    assert [tool["name"] for tool in enabled["tools"]] == ["fetch_video", "search-posts"]
    assert next(tool for tool in enabled["tools"] if tool["name"] == "fetch_video")["description"] == "取一条", "重名的留先报的那个"
    node_types = {one["type"] for one in client.get("/api/workflows/node-types").json()}
    assert "plugin.dev.mcpnames.fetch_video" in node_types and not any("files" in one for one in node_types)
