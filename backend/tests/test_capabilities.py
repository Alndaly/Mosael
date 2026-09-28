"""宿主能力是一张表、一套挑法(ADR 0031 §5):素材外链和文档解析登记同一种契约,设置页一页列全。

钉住的几件事:
- 有内置实现的能力(文档解析)**没定默认就用内置的**;装了一家配好的云端解析也不会悄悄换过去(文档是原件,
  交出去必须他自己定过);
- 定了插件就用插件;选回内置的 = 清掉默认;只能定自己的、声明了这项能力的连接;
- 插件太旧 / 没配好时各说各的下一步;
- 清单里 `document_parse` 是只给宿主调的能力:只给进程形态、有且只有一个工具认领。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginCredential, PluginInstance, PluginPackage
from tests.util import fresh_client

PARSER = {
    "id": "dev.test.parser", "manifest_version": 1, "name": "解析", "version": "1",
    "provides": ["document_parse"],
    "runtime": {"kind": "process", "entry": "main.py"},
    "instance": {"credentials": [{"key": "TOKEN", "label": "Token", "required": True}]},
    "tools": {"declare": [{"name": "parse", "provides": ["document_parse"]}]},
}


def _me(client) -> str:
    return client.get("/api/auth/me").json()["id"]


def _parser(owner: str, name: str, *, configured: bool = True) -> str:
    with SessionLocal() as db:
        if db.get(PluginPackage, PARSER["id"]) is None:
            db.add(PluginPackage(id=PARSER["id"], name="解析", version="1", manifest=PARSER))
            db.flush()
        instance = PluginInstance(owner_user_id=owner, package_id=PARSER["id"], name=name, enabled=True, config={})
        db.add(instance)
        db.flush()
        if configured:
            db.add(PluginCredential(instance_id=instance.id, key="TOKEN", value="t"))
        db.commit()
        return instance.id


def _documents(client) -> dict:
    return next(one for one in client.get("/api/settings/capabilities").json() if one["capability"] == "document_parse")


def test_设置页按能力表列出每一项能力() -> None:
    client = fresh_client()
    listed = client.get("/api/settings/capabilities").json()
    assert [one["capability"] for one in listed] == ["audio_denoise", "audio_separation", "document_parse", "public_url", "transcription", "translation"]
    #: 本机引擎是内置提供方(ADR 0032),和插件连接并列;没定默认用第一个允许自动、跑得起来的。
    denoise = listed[0]
    assert [one["id"] for one in denoise["options"]][:1] == ["builtin:ffmpeg"] and denoise["automatic"] == "builtin:ffmpeg"
    documents = listed[2]
    assert documents["options"] == [{"id": "builtin:local", "name": "本地解析", "builtin": True, "missing": []}]
    assert documents["current"] is None and documents["automatic"] == "builtin:local"
    #: 每项能力下面列「用在哪」(ADR 0032 §4):定了这一家,哪些地方跟着换 —— 现算,不手写。
    kinds = {one["kind"] for one in documents["used_by"]}
    assert kinds == {"app", "workflow", "agent"}
    assert any("降噪" in one["label"] for one in denoise["used_by"] if one["kind"] == "workflow")
    assert not any("设成默认" in one["label"] for one in documents["used_by"]), "设置页里不再说「在设置里设成默认」"


def test_文档解析没定默认就用本地的_配好了云端也不悄悄换() -> None:
    from app.domain import capabilities, documents

    client = fresh_client()
    me = _me(client)
    cloud = _parser(me, "MinerU 云端")
    state = _documents(client)
    assert [one["id"] for one in state["options"]] == ["builtin:local", cloud], "内置的排第一"
    assert state["automatic"] == "builtin:local"
    with SessionLocal() as db:
        assert capabilities.choose(db, me, documents.CAPABILITY).id == "builtin:local"

    chosen = client.put("/api/settings/capabilities/document_parse", json={"provider_id": cloud}).json()
    assert chosen["current"] == cloud
    with SessionLocal() as db:
        picked = capabilities.choose(db, me, documents.CAPABILITY)
        assert picked.id == cloud and picked.tool == "parse" and not picked.builtin

    #: 选回本地 = 清掉默认。
    back = client.put("/api/settings/capabilities/document_parse", json={"provider_id": "builtin:local"}).json()
    assert back["current"] is None and back["automatic"] == "builtin:local"


def test_定的那家没配好_说清楚缺什么_怎么换回本地() -> None:
    from app.domain import capabilities, documents

    client = fresh_client()
    me = _me(client)
    broken = _parser(me, "MinerU 云端", configured=False)
    client.put("/api/settings/capabilities/document_parse", json={"provider_id": broken})
    with SessionLocal() as db, pytest.raises(documents.DocumentParserUnavailable) as raised:
        capabilities.choose(db, me, documents.CAPABILITY)
    assert raised.value.key == "docErr_parserIncomplete"
    assert "Token" in str(raised.value) and "本地解析" in str(raised.value)


def test_权限没授予也算没配好_下拉里选不到_和真调用时同一道门() -> None:
    """设置页和真解析问的是同一件事:没授予 network 权限的连接,真调用时 blocked_reason 会挡回来,
    那设置页就不该让人选它。"""
    from app.domain import capabilities, documents

    client = fresh_client()
    me = _me(client)
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.test.parser-net", name="解析", version="1",
                             manifest={**PARSER, "id": "dev.test.parser-net", "permissions": ["network:mineru.net"]}))
        db.flush()
        instance = PluginInstance(owner_user_id=me, package_id="dev.test.parser-net", name="MinerU 云端",
                                  enabled=True, config={})
        db.add(instance)
        db.flush()
        db.add(PluginCredential(instance_id=instance.id, key="TOKEN", value="t"))
        db.commit()
        cloud = instance.id

    option = next(one for one in _documents(client)["options"] if one["id"] == cloud)
    assert option["missing"] == ["插件权限(到插件页授予)"]
    client.put("/api/settings/capabilities/document_parse", json={"provider_id": cloud})
    with SessionLocal() as db, pytest.raises(documents.DocumentParserUnavailable) as raised:
        capabilities.choose(db, me, documents.CAPABILITY)
    assert raised.value.key == "docErr_parserIncomplete" and "插件权限" in str(raised.value)

    granted = client.patch(f"/api/plugins/instances/{cloud}/permissions", json={"grants": {"network:mineru.net": True}})
    assert granted.status_code == 200
    option = next(one for one in _documents(client)["options"] if one["id"] == cloud)
    assert option["missing"] == []
    with SessionLocal() as db:
        assert capabilities.choose(db, me, documents.CAPABILITY).id == cloud


def test_不能定别人的连接_也不能定没声明这项能力的() -> None:
    from tests.util import second_client

    client = fresh_client()
    mine = _parser(_me(client), "我的")
    other = second_client()
    assert other.put("/api/settings/capabilities/document_parse", json={"provider_id": mine}).status_code == 400
    assert client.put("/api/settings/capabilities/nope", json={"provider_id": None}).status_code == 404


@pytest.mark.parametrize(("patch", "key"), [
    ({"runtime": {"kind": "mcp", "command": "x"}}, "pluginErr_manifestCapabilityNeedsProcess"),
    ({"tools": {"declare": [{"name": "parse"}]}}, "pluginErr_manifestCapabilityUnclaimed"),
    ({"tools": {"declare": [{"name": "a", "provides": ["document_parse"]}, {"name": "b", "provides": ["document_parse"]}]}},
     "pluginErr_manifestCapabilityClaimedTwice"),
])
def test_清单里文档解析只给宿主调_规矩和生成一样(patch: dict, key: str) -> None:
    from app.domain.plugins.manifest import ManifestError, parse

    parse(PARSER, "/tmp/x")
    with pytest.raises(ManifestError) as raised:
        parse({**PARSER, **patch}, "/tmp/x")
    assert raised.value.key == key


def test_点名自动用的那个之外的内置实现_存下来_挑的时候用它() -> None:
    """降噪三个本机引擎:点名 RNNoise 此前报「没有这个连接」(用户截图)—— 默认那张表只认插件连接。"""
    from app.domain import audio_capabilities, capabilities

    client = fresh_client()
    me = _me(client)
    denoise = audio_capabilities.DENOISE
    other = next(one.id for one in denoise.builtins if one.id != "builtin:ffmpeg")
    response = client.put("/api/settings/capabilities/audio_denoise", json={"provider_id": other})
    assert response.status_code == 200, response.text
    assert response.json()["current"] == other
    with SessionLocal() as db:
        assert capabilities.choices(db, me, denoise)["current"] == other

    #: 选回自动用的那个 = 清掉默认。
    back = client.put("/api/settings/capabilities/audio_denoise", json={"provider_id": "builtin:ffmpeg"}).json()
    assert back["current"] is None
