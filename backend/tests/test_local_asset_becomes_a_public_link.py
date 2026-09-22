"""某个角色只收链接、而素材是本地的 —— **自动传上去**,而不是把问题退回给用户。

## 现场

Mosael 是本地优先的:素材在用户自己的盘上,没有公网地址。而方舟 Seedance 的参考视频
**只收链接**(参考图可以走 Base64,参考视频不行,官方文档明写),视频编辑/续写的源视频同理。

最早这条路的结局是花钱之后才来的一句英文 400;上一步改成了提交前拦住并说清原因 ——
但那仍然是**把问题退回给用户**:他得自己找个对象存储、自己传、自己签链接、再粘回来,
而这四步里每一步都可能做错。

现在多一步:提交时看见这种角色带的是本地素材,就找一个**声明了 `public_url` 能力**的插件
传上去。用户那一侧只是多等几秒。

## 三种失败各说各的

它们对用户意味着完全不同的下一步,所以不能合成一句:没装(去装哪几个)/ 装了没配好
(点名是哪一个、缺什么)/ 传失败(把插件自己的话带出来)。
"""

from __future__ import annotations

import pytest

from app.domain.generation.public_links import NoUploader, public_url_for


class _Instance:
    def __init__(self, name: str, enabled: bool = True) -> None:
        self.id, self.name, self.enabled = f"inst-{name}", name, enabled


class _Manifest:
    def __init__(self, provides: list[str]) -> None:
        self.provides = provides


class _Invocation:
    def __init__(self, status: str, output: dict) -> None:
        self.status, self.output, self.error = status, output, ""


def _patch(monkeypatch, *, instances, manifests, missing=None, invoke=None, tools=None):
    from app.domain.plugins import instances as inst
    from app.domain.plugins import tools as plugin_tools
    from app.domain.generation import public_links

    class _Query:
        def all(self):
            return instances

    db = type("DB", (), {"query": lambda self, model: _Query()})()
    monkeypatch.setattr(inst, "manifest_for", lambda _db, instance: manifests[instance.name])
    monkeypatch.setattr(inst, "missing_config", lambda _db, instance: (missing or {}).get(instance.name, []))
    monkeypatch.setattr(plugin_tools, "all_tools", lambda _db, instance: tools or [{"name": "tos_upload"}])
    if invoke is not None:
        monkeypatch.setattr(plugin_tools, "invoke", invoke)
    assert public_links.PUBLIC_URL == "public_url"
    return db


def test_装了插件就自动传_并说出用的是哪一个(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_invoke(db, instance_id, tool_name, payload, **kwargs):
        calls.append({"instance": instance_id, "tool": tool_name, "payload": payload})
        return _Invocation("succeeded", {"url": "https://cdn.example.com/x.mp4?sig=1"})

    db = _patch(monkeypatch,
                instances=[_Instance("火山引擎 TOS · bucket")],
                manifests={"火山引擎 TOS · bucket": _Manifest(["public_url"])},
                invoke=fake_invoke)

    url, via = public_url_for(db, workspace_id="ws", asset_id="a1", asset_name="入殿推进.mp4")

    assert url == "https://cdn.example.com/x.mp4?sig=1"
    assert via == "火山引擎 TOS · bucket", "没说清用的是哪一个插件 —— 用户的桶里凭空多了个文件"
    assert calls[0]["tool"] == "tos_upload"
    assert calls[0]["payload"]["asset_id"] == "a1"


def test_没装插件时_说的是去装哪几个(monkeypatch) -> None:
    """**不是"请自行上传到公开地址"** —— 那句话没有告诉用户任何可执行的下一步。"""
    db = _patch(monkeypatch, instances=[], manifests={})

    with pytest.raises(NoUploader) as raised:
        public_url_for(db, workspace_id="ws", asset_id="a1", asset_name="入殿推进.mp4")
    message = str(raised.value)
    assert "对象存储插件" in message
    assert "TOS" in message and "OSS" in message and "S3" in message
    assert "入殿推进.mp4" in message, "没说是哪一份素材"


def test_装了但没配好_点名是哪一个_缺什么(monkeypatch) -> None:
    db = _patch(monkeypatch,
                instances=[_Instance("阿里云 OSS · 未配置")],
                manifests={"阿里云 OSS · 未配置": _Manifest(["public_url"])},
                missing={"阿里云 OSS · 未配置": ["OSS_BUCKET", "OSS_ACCESS_KEY_ID"]})

    with pytest.raises(NoUploader) as raised:
        public_url_for(db, workspace_id="ws", asset_id="a1", asset_name="clip.mp4")
    message = str(raised.value)
    assert "阿里云 OSS · 未配置" in message and "OSS_BUCKET" in message


def test_传失败时_把插件自己的话带出来(monkeypatch) -> None:
    """桶不存在、密钥没权限、网络不通 —— 这几种只有插件说得清,吞掉就只剩"上传失败"。"""
    db = _patch(monkeypatch,
                instances=[_Instance("TOS")],
                manifests={"TOS": _Manifest(["public_url"])},
                invoke=lambda *a, **k: _Invocation("failed", {"error": "403 AccessDenied:这把密钥没有写权限"}))

    with pytest.raises(NoUploader, match="没有写权限"):
        public_url_for(db, workspace_id="ws", asset_id="a1", asset_name="clip.mp4")


def test_没声明能力的插件不会被当成对象存储(monkeypatch) -> None:
    """**按声明找,不按名字猜。** 猜错的表现是把用户的素材传去了别的地方。"""
    db = _patch(monkeypatch,
                instances=[_Instance("某个也有 upload 工具的插件")],
                manifests={"某个也有 upload 工具的插件": _Manifest([])})

    with pytest.raises(NoUploader, match="对象存储插件"):
        public_url_for(db, workspace_id="ws", asset_id="a1", asset_name="clip.mp4")


def test_多个可用时选哪一个是稳定的(monkeypatch) -> None:
    """同一份素材这次传去 TOS、下次传去 OSS 的话,用户看不出为什么。"""
    from app.domain.generation.public_links import uploaders

    names = ["Z 最后", "A 最前", "M 中间"]
    db = _patch(monkeypatch,
                instances=[_Instance(name) for name in names],
                manifests={name: _Manifest(["public_url"]) for name in names})

    picked = [instance.name for instance, _ in uploaders(db, "ws")]
    assert picked == sorted(names), "选择顺序不稳定"


def test_三个官方插件都声明了这个能力() -> None:
    import json
    from pathlib import Path

    from app.domain.plugins.manifest import parse

    root = Path(__file__).resolve().parents[2] / "plugins" / "examples"
    for name in ("aws-s3", "volcengine-tos", "aliyun-oss"):
        manifest = parse(json.loads((root / name / "mosael.plugin.json").read_text(encoding="utf-8")), name)
        assert "public_url" in manifest.provides, f"{name} 没声明 public_url —— 宿主找不到它"
