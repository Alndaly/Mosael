"""资产和社区之间(ADR 0027 §4):分享一个资产(连同变体)、真人要确认、同一个链接发新版本;从社区导入、按哈希核对、
导入的真人授权「待你确认」、看社区上有没有新版本。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from mosael_formats.asset_bundle import SCHEMA
from PIL import Image

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Entity
from tests.community_fake import ORIGIN, FakeCommunity, connect, install


def _png(color: str, size: tuple[int, int] = (64, 48)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset(ws: str, asset_id: str, data: bytes, filename: str, kind: str = "image") -> Path:
    directory = settings.media_dir / "assets" / ws / asset_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(data)
    with SessionLocal() as db:
        db.add(Asset(id=asset_id, workspace_id=ws, kind=kind, name=asset_id,
                     file_key=str(path.relative_to(settings.data_dir)), media_info={"width": 64, "height": 48}))
        db.commit()
    return path


def _setup(monkeypatch, *, connected: bool = True) -> tuple[FakeCommunity, Any, str]:
    fake, client, clock = install(monkeypatch)
    if connected:
        connect(client, fake, clock)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return fake, client, ws


def _character(client, ws: str, name: str = "林小满", **attributes: Any) -> dict:
    made = client.post("/api/entities", json={
        "workspace_id": ws, "kind": "character", "name": name, "description": "短片女主角",
        "prompt": "a girl with short black hair", "tags": ["主角"], "attributes": attributes,
    })
    assert made.status_code == 200, made.text
    return made.json()


def _publish(client, ws: str, entity_id: str, **body: Any):
    return client.post(f"/api/entities/{entity_id}/community", json={"workspace_id": ws, **body})


def _remote_bundle(front: bytes, side: bytes, winter: bytes, *, real_person: bool = False) -> dict:
    return {
        "schema": SCHEMA,
        "kind": "character",
        "name": "阿澄",
        "description": "别人发的人物",
        "prompt": "a tall boy",
        "tags": ["配角"],
        "attributes": {"real_person": real_person, "blockout_color": "#3366aa"},
        "references": [
            {"sha256": _sha(front), "content_type": "image/png", "width": 64, "height": 48, "role": "front"},
            {"sha256": _sha(side), "content_type": "image/png", "width": 64, "height": 48, "role": "side"},
        ],
        "cover_sha256": _sha(side),
        "variants": [{
            "name": "冬装", "description": "", "prompt": "winter coat", "tags": [], "attributes": {},
            "references": [
                {"sha256": _sha(winter), "content_type": "image/png", "role": "front"},
                # 母体的那张在变体里再出现一次:只下载、只导入一次。
                {"sha256": _sha(front), "content_type": "image/png", "role": "side"},
            ],
            "cover_sha256": _sha(winter),
        }],
    }


# --- 分享 ---------------------------------------------------------------------


def test_分享一个人物_带变体_只带图_再发是同一个链接的新版本(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    front, side, winter = _png("red"), _png("green"), _png("blue")
    _asset(ws, "a-front", front, "front.png")
    _asset(ws, "a-side", side, "side.png")
    _asset(ws, "a-winter", winter, "winter.png")
    _asset(ws, "a-clip", b"not-really-a-video", "clip.mp4", kind="video")
    made = _character(client, ws, blockout_color="#aabbcc")
    eid = made["id"]
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "a-front"})
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "a-side", "role": "side", "cover": True})
    client.post(f"/api/entities/{eid}/references", json={"asset_id": "a-clip", "role": "concept"})
    variant = client.post(f"/api/entities/{eid}/variants", json={"name": "冬装", "prompt": "winter coat"}).json()
    client.post(f"/api/entities/{variant['id']}/references", json={"asset_id": "a-winter"})

    published = _publish(client, ws, eid, title="林小满 · 短片女主角", tags=["主角", "短片"])
    assert published.status_code == 200, published.text
    out = published.json()
    assert out["status"] == "approved" and out["version"] == "1"
    assert out["url"] == f"{ORIGIN}/assets/{out['slug']}"

    sent = fake.assets[out["slug"]]["versions"][0]
    bundle = sent["bundle"]
    assert [(one["role"], one["sha256"]) for one in bundle["references"]] == [("front", _sha(front)), ("side", _sha(side))], \
        "视频参考不出门"
    assert bundle["cover_sha256"] == _sha(side)
    assert [one["name"] for one in bundle["variants"]] == ["冬装"]
    assert bundle["variants"][0]["references"][0]["sha256"] == _sha(winter)
    assert sent["fields"]["title"] == "林小满 · 短片女主角" and sent["fields"]["tags"] == ["主角", "短片"]
    assert "consent_kind" not in sent["fields"], "虚构人物不带授权声明"
    assert set(fake.puts) == {_sha(front), _sha(side), _sha(winter)}

    state = client.get(f"/api/entities/{eid}/community").json()
    assert state["published"]["slug"] == out["slug"] and state["source"] is None
    assert state["status"]["connected"] is True

    again = _publish(client, ws, eid).json()
    assert again["slug"] == out["slug"] and again["version"] == "2"
    assert len(fake.puts) == 3, "社区已经有的图不再传"


def test_真人人物_要本机声明过_这一次还要确认_然后先审核(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    face = _png("pink")
    _asset(ws, "a-face", face, "face.png")
    undeclared = _character(client, ws, "主播", real_person=True)
    client.post(f"/api/entities/{undeclared['id']}/references", json={"asset_id": "a-face"})
    refused = _publish(client, ws, undeclared["id"], consent_confirmed=True)
    assert refused.status_code == 422
    assert "授权" in refused.json()["detail"]

    client.patch(f"/api/entities/{undeclared['id']}", json={"attributes": {"real_person": True, "consent": {"kind": "self"}}})
    unconfirmed = _publish(client, ws, undeclared["id"])
    assert unconfirmed.status_code == 422, "这一次没有确认「已获得本人同意公开」"
    assert fake.assets == {}

    published = _publish(client, ws, undeclared["id"], consent_confirmed=True).json()
    assert published["status"] == "pending"
    assert fake.assets[published["slug"]]["versions"][0]["consent_kind"] == "self"
    assert client.get(f"/api/entities/{undeclared['id']}/community").json()["published"]["status"] == "pending"


def test_变体不能单独发_没有图的发不了_没连账号发不了(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch, connected=False)
    _asset(ws, "a-one", _png("gray"), "one.png")
    parent = _character(client, ws)
    variant = client.post(f"/api/entities/{parent['id']}/variants", json={"name": "冬装"}).json()
    assert _publish(client, ws, variant["id"]).status_code == 422
    assert _publish(client, ws, parent["id"]).status_code == 409, "没连社区账号"
    assert fake.assets == {}


def test_没有图的资产不往外发(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch)
    lonely = _character(client, ws)
    refused = _publish(client, ws, lonely["id"])
    assert refused.status_code == 422
    assert fake.assets == {}


def test_工作区对不上当作不存在_viewer_发不了(monkeypatch) -> None:
    _fake, client, ws = _setup(monkeypatch)
    other = client.post("/api/workspaces", json={"name": "X"}).json()["id"]
    made = _character(client, ws)
    assert _publish(client, other, made["id"]).status_code == 404


# --- 导入 ---------------------------------------------------------------------


def test_浏览社区资产_图片地址是完整的(monkeypatch) -> None:
    fake, client, _ws = _setup(monkeypatch, connected=False)
    front, side, winter = _png("red"), _png("green"), _png("blue")
    fake.publish_asset(_remote_bundle(front, side, winter), {_sha(one): one for one in (front, side, winter)})
    page = client.get("/api/community/assets", params={"asset_kind": "character"})
    assert page.status_code == 200, page.text
    [item] = page.json()["items"]
    assert item["title"] == "阿澄" and item["author_name"] == "Bob" and item["variant_count"] == 1
    assert item["cover_url"].startswith(ORIGIN)
    assert client.get("/api/community/assets", params={"asset_kind": "prop"}).json()["items"] == []


def test_贴链接导入_图按哈希核对_建资产和变体_记下来源_看得到新版本(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch, connected=False)
    front, side, winter = _png("red"), _png("green"), _png("blue")
    slug = fake.publish_asset(_remote_bundle(front, side, winter), {_sha(one): one for one in (front, side, winter)})

    imported = client.post("/api/entities/import-community",
                           json={"workspace_id": ws, "link": f"{ORIGIN}/zh/assets/{slug}?from=share"})
    assert imported.status_code == 200, imported.text
    entity = imported.json()
    assert entity["name"] == "阿澄" and entity["kind"] == "character" and entity["tags"] == ["配角"]
    assert entity["attributes"]["blockout_color"] == "#3366aa"
    assert [one["role"] for one in entity["references"]] == ["front", "side"]
    assert entity["cover_asset_id"] == entity["references"][1]["asset_id"]
    assert [one["name"] for one in entity["variants"]] == ["冬装"]
    assert "consent" not in entity["attributes"], "虚构人物不需要授权声明"
    assert fake.count("storage:/media/" + _sha(front)) == 1, "母体和变体共用的那张只下载一次"

    variant = client.get(f"/api/entities/{entity['variants'][0]['id']}").json()
    assert [one["role"] for one in variant["references"]] == ["front", "side"]
    assert variant["references"][1]["asset_id"] == entity["references"][0]["asset_id"], "同一张图只导入成一份素材"
    with SessionLocal() as db:
        sources = {asset.source for asset in db.query(Asset).filter(Asset.workspace_id == ws)}
    assert sources == {"community"}

    state = client.get(f"/api/entities/{entity['id']}/community").json()
    assert state["source"]["slug"] == slug and state["source"]["version"] == "1"
    assert state["latest_version"] == "1" and state["published"] is None

    fake.publish_asset(_remote_bundle(front, side, winter), {}, slug=slug)
    assert client.get(f"/api/entities/{entity['id']}/community").json()["latest_version"] == "2"


def test_导入的真人人物_授权待本机确认_确认之前不能用于数字人(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch, connected=False)
    front, side, winter = _png("red"), _png("green"), _png("blue")
    slug = fake.publish_asset(_remote_bundle(front, side, winter, real_person=True),
                              {_sha(one): one for one in (front, side, winter)})
    entity = client.post("/api/entities/import-community", json={"workspace_id": ws, "link": slug}).json()
    assert entity["attributes"]["real_person"] is True
    assert entity["attributes"]["consent"]["kind"] == "pending"
    assert entity["usable_for_digital_human"] is False

    # 「待确认」只能由导入产生,不能自己写上去。
    other = _character(client, ws, "别人", real_person=True)
    forged = client.patch(f"/api/entities/{other['id']}", json={"attributes": {"real_person": True, "consent": {"kind": "pending"}}})
    assert forged.status_code == 422

    # 保存别的字段时原样带回「待确认」不算改它。
    kept = client.patch(f"/api/entities/{entity['id']}", json={"attributes": {**entity["attributes"], "blockout_color": "#000000"}})
    assert kept.status_code == 200, kept.text
    assert kept.json()["attributes"]["consent"]["kind"] == "pending"

    confirmed = client.patch(f"/api/entities/{entity['id']}",
                             json={"attributes": {**entity["attributes"], "consent": {"kind": "authorized"}}}).json()
    assert confirmed["attributes"]["consent"]["kind"] == "authorized"
    assert confirmed["usable_for_digital_human"] is True


def test_图对不上哈希就什么都不建(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch, connected=False)
    front, side, winter = _png("red"), _png("green"), _png("blue")
    slug = fake.publish_asset(_remote_bundle(front, side, winter), {_sha(one): one for one in (front, side, winter)})
    fake.tampered.add(_sha(winter))
    refused = client.post("/api/entities/import-community", json={"workspace_id": ws, "link": slug})
    assert refused.status_code == 422
    with SessionLocal() as db:
        assert db.query(Entity).filter(Entity.workspace_id == ws).count() == 0
        assert db.query(Asset).filter(Asset.workspace_id == ws).count() == 0


def test_链接不对_条目不存在(monkeypatch) -> None:
    _fake, client, ws = _setup(monkeypatch, connected=False)
    for bad in ("", "https://community.test/zh/assets/", "Not A Slug!"):
        assert client.post("/api/entities/import-community", json={"workspace_id": ws, "link": bad}).status_code == 422, bad
    # 链接里的站点不算数:只向部署设置里的那个社区要东西。
    elsewhere = client.post("/api/entities/import-community", json={"workspace_id": ws, "link": "https://evil.test/assets/nobody"})
    assert elsewhere.status_code == 404
    assert client.post("/api/entities/import-community", json={"workspace_id": ws, "link": "nobody-here"}).status_code == 404


def test_社区地址上不是社区服务_说清楚去改地址而不是说条目不存在(monkeypatch) -> None:
    fake, client, ws = _setup(monkeypatch, connected=False)
    fake.just_a_website = True
    browsed = client.get("/api/community/assets", headers={"Accept-Language": "zh"})
    assert browsed.status_code == 502, browsed.text
    detail = browsed.json()["detail"]
    assert ORIGIN in detail and "部署设置" in detail, detail
    imported = client.post("/api/entities/import-community", json={"workspace_id": ws, "link": "someone"})
    assert imported.status_code == 502, "不是「这一条不存在」(404)"
