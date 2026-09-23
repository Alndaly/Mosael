"""某个角色只收链接、而素材是本地的 —— **自动传上去**,而不是把问题退回给用户。

## 现场

Mosael 是本地优先的:素材在用户自己的盘上,没有公网地址。而方舟 Seedance 的参考视频
**只收链接**(参考图可以走 Base64,参考视频不行,官方文档明写),视频编辑/续写的源视频同理。
提交时看见这种角色带的是本地素材,就找一个**声明了 `public_url` 能力**的插件传上去。

## 用哪一家(第二版)

第一版按实例名字母序取整个部署里的第一个,三个问题:

- **不看归属** —— 多人部署时,A 的素材会用 B 的桶和密钥传上去;
- 排第一的没配好就直接报错,不换配好的那一家;配了几家时用哪家取决于它叫什么;
- 同一份素材每次生成都重传一遍。

现在:只看发起人自己的、配好的;配好一家就用它,几家就用他定的默认,没定就当场问。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginCapabilityDefault, PluginCredential, PluginInstance, PluginPackage
from app.domain.generation.public_links import NoUploader, public_url_for
from tests.util import fresh_client, make_video_asset

STORAGE = {
    "id": "dev.test.storage", "manifest_version": 1, "name": "存储", "version": "1",
    "provides": ["public_url"],
    "runtime": {"kind": "process", "entry": "main.py"},
    "instance": {
        "multiple": True,
        "config": [{"key": "BUCKET", "label": "桶名", "type": "string", "required": True}],
        "credentials": [{"key": "SECRET", "label": "密钥", "required": True}],
    },
    "tools": {"declare": [
        {"name": "st_list"},
        {"name": "st_put", "provides": ["public_url"]},
    ]},
}


class _Invocation:
    def __init__(self, status: str, output: dict) -> None:
        self.status, self.output, self.error = status, output, ""


@pytest.fixture
def world(monkeypatch):
    """一个工作区 + 一份本地素材 + 一个假的上传工具(记下每次调了谁)。"""
    from app.domain.plugins import tools as plugin_tools

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset = make_video_asset(client, ws)
    calls: list[dict] = []

    def fake_invoke(db, instance_id, tool_name, payload, **kwargs):
        calls.append({"instance": instance_id, "tool": tool_name})
        return _Invocation("succeeded", {"url": f"https://cdn.example.com/{instance_id}/{len(calls)}"})

    monkeypatch.setattr(plugin_tools, "invoke", fake_invoke)
    with SessionLocal() as db:
        db.add(PluginPackage(id=STORAGE["id"], name="存储", version="1", manifest=STORAGE))
        db.commit()
    return {"ws": ws, "asset": asset["id"], "calls": calls}


def _storage(owner: str, name: str, *, configured: bool = True, manifest_id: str = STORAGE["id"]) -> str:
    with SessionLocal() as db:
        instance = PluginInstance(owner_user_id=owner, package_id=manifest_id, name=name, enabled=True,
                                  config={"BUCKET": "b"} if configured else {})
        db.add(instance)
        db.flush()
        if configured:
            db.add(PluginCredential(instance_id=instance.id, key="SECRET", value="s"))
        db.commit()
        return instance.id


def _upload(world, owner: str = "alice") -> tuple[str, str]:
    with SessionLocal() as db:
        return public_url_for(db, owner_user_id=owner, workspace_id=world["ws"],
                              asset_id=world["asset"], asset_name="入殿推进.mp4")


def test_只用发起人自己的存储_不碰别人的桶(world) -> None:
    """多人部署:bob 配了存储、alice 没配。alice 的素材不能用 bob 的桶和密钥传上去。"""
    _storage("bob", "bob 的 OSS")

    with pytest.raises(NoUploader, match="对象存储插件"):
        _upload(world, owner="alice")
    assert world["calls"] == [], "用别人的存储传了"


def test_配好一家就用它_并说出用的是哪一家(world) -> None:
    mine = _storage("alice", "我的 TOS")

    url, via = _upload(world)

    assert via == "我的 TOS"
    assert world["calls"] == [{"instance": mine, "tool": "st_put"}], "上传工具要按声明找,不按名字猜"
    assert url.startswith("https://cdn.example.com/")


def test_排第一的没配好时_用配好的那一家(world) -> None:
    """此前按名字取第一个,它没配好就整条报错 —— 哪怕另一家配得好好的。"""
    _storage("alice", "A 没配好", configured=False)
    ready = _storage("alice", "Z 配好了")

    _url, via = _upload(world)
    assert via == "Z 配好了"
    assert world["calls"][0]["instance"] == ready


def test_配好了几家却没定默认_当场问而不是替他挑(world) -> None:
    _storage("alice", "阿里云 OSS")
    _storage("alice", "腾讯云 COS")

    with pytest.raises(NoUploader) as raised:
        _upload(world)
    message = str(raised.value)
    assert "阿里云 OSS" in message and "腾讯云 COS" in message
    assert "设置 → 视频生成" in message and "素材外链" in message, "没说去哪儿定"
    assert world["calls"] == []


def test_定了默认就用默认那家(world) -> None:
    _storage("alice", "阿里云 OSS")
    cos = _storage("alice", "腾讯云 COS")
    with SessionLocal() as db:
        db.add(PluginCapabilityDefault(owner_user_id="alice", capability="public_url", instance_id=cos))
        db.commit()

    _url, via = _upload(world)
    assert via == "腾讯云 COS"


def test_一家都没配好_点名是哪一个_缺什么(world) -> None:
    _storage("alice", "阿里云 OSS · 未配置", configured=False)

    with pytest.raises(NoUploader) as raised:
        _upload(world)
    message = str(raised.value)
    assert "阿里云 OSS · 未配置" in message and "桶名" in message and "密钥" in message


def test_没装时说去装哪几家(world) -> None:
    with pytest.raises(NoUploader) as raised:
        _upload(world)
    message = str(raised.value)
    for vendor in ("TOS", "OSS", "COS", "S3"):
        assert vendor in message
    assert "入殿推进.mp4" in message, "没说是哪一份素材"


def test_同一份素材不重复上传(world) -> None:
    _storage("alice", "我的 TOS")

    first, _ = _upload(world)
    second, _ = _upload(world)

    assert first == second
    assert len(world["calls"]) == 1, "链接还在有效期里,却又传了一遍"


def test_传失败时_把插件自己的话带出来(world, monkeypatch) -> None:
    from app.domain.plugins import tools as plugin_tools

    _storage("alice", "TOS")
    monkeypatch.setattr(plugin_tools, "invoke",
                        lambda *a, **k: _Invocation("failed", {"error": "403 AccessDenied:这把密钥没有写权限"}))

    with pytest.raises(NoUploader, match="没有写权限"):
        _upload(world)


def test_插件版本太旧_没有工具认领上传时让他去更新(world) -> None:
    """包上声明了能换公网地址,却没有哪个工具说「这件事归我」—— 那是写 provides 之前的老版本。"""
    old = {**STORAGE, "id": "dev.test.old", "tools": {"declare": [{"name": "st_put"}]}}
    with SessionLocal() as db:
        db.add(PluginPackage(id=old["id"], name="旧存储", version="0", manifest=old))
        db.commit()
    _storage("alice", "旧版存储", manifest_id=old["id"])

    with pytest.raises(NoUploader, match="更新"):
        _upload(world)


def test_工具声明了包上没有的能力_清单当场拒绝() -> None:
    from app.domain.plugins.manifest import ManifestError, parse

    wrong = {**STORAGE, "provides": []}
    with pytest.raises(ManifestError, match="public_url"):
        parse(wrong, "x")


def test_官方的对象存储插件都声明了这个能力_也声明了由哪个工具来做() -> None:
    import json
    from pathlib import Path

    from app.domain.plugins.manifest import parse

    root = Path(__file__).resolve().parents[2] / "plugins" / "examples"
    for name in ("aws-s3", "volcengine-tos", "aliyun-oss", "tencent-cos"):
        manifest = parse(json.loads((root / name / "mosael.plugin.json").read_text(encoding="utf-8")), name)
        assert "public_url" in manifest.provides, f"{name} 没声明 public_url —— 宿主找不到它"
        assert manifest.tool_providing("public_url").endswith("_upload"), f"{name} 没说哪个工具负责上传"


def test_在设置里选素材外链用哪一家_只能选自己的() -> None:
    """配了几家存储时用哪一家,是个人的选择 —— 和默认模型一样放在设置里(视频生成页)。"""
    from tests.test_plugins import install
    from tests.util import second_client

    client = install({**STORAGE, "id": "dev.test.storage2"})
    me = client.get("/api/auth/me").json()["id"]
    first = _storage(me, "阿里云 OSS", manifest_id="dev.test.storage2")
    second = _storage(me, "腾讯云 COS", manifest_id="dev.test.storage2")
    _storage(me, "没配好的", configured=False, manifest_id="dev.test.storage2")

    state = client.get("/api/settings/asset-link-storage").json()
    assert state["current"] is None and state["automatic"] is None, "几家都配好了,不该替他挑"
    assert {o["name"]: o["missing"] for o in state["options"]}["没配好的"] == ["桶名", "密钥"]

    chosen = client.put("/api/settings/asset-link-storage", json={"instance_id": second}).json()
    assert chosen["current"] == second

    # 别人不能把我的连接定成他的,也看不到我的存储。
    other = second_client()
    assert other.put("/api/settings/asset-link-storage", json={"instance_id": first}).status_code == 400
    assert other.get("/api/settings/asset-link-storage").json()["options"] == []

    cleared = client.put("/api/settings/asset-link-storage", json={"instance_id": None}).json()
    assert cleared["current"] is None


def test_只配好一家时_设置里显示会自动用它(world) -> None:
    only = _storage("alice", "我的 TOS")
    _storage("alice", "没配好的", configured=False)
    from app.domain.generation.public_links import storage_choices

    with SessionLocal() as db:
        state = storage_choices(db, "alice")
    assert state["current"] is None and state["automatic"] == only
