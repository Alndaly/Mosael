"""参考库(ADR 0091 §3):只读目录、单条取用、出处、保存成资产。"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Entity, PluginInstance, PluginPackage, User
from app.domain import reference_library
from tests.util import fresh_client


PACKAGE_ID = "dev.test.reference-library"

MANIFEST = {
    "id": PACKAGE_ID,
    "name": "测试参考库",
    "version": "1.0.0",
    "manifest_version": 1,
    "runtime": {"kind": "process", "entry": "main.py"},
    "provides": ["reference_library"],
    "tools": {"declare": [{"name": "host", "provides": ["reference_library"], "timeout_seconds": 60,
                           "input_schema": {"type": "object"}}]},
}


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 64), (120, 130, 140)).save(buffer, "PNG")
    return buffer.getvalue()


def _setup() -> tuple[Any, str, PluginInstance]:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "参考"}).json()["id"]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "tester"))
        db.add(PluginPackage(id=PACKAGE_ID, name="测试参考库", version="1.0.0", manifest=MANIFEST))
        db.flush()
        instance = PluginInstance(owner_user_id=user.id, package_id=PACKAGE_ID, name="姿势图集", enabled=True,
                                  config={}, discovered_tools=[], capability_status={}, package_sources={},
                                  applied_moves={})
        db.add(instance)
        db.commit()
        db.refresh(instance)
        return client, workspace, instance


def _fake_tools(monkeypatch):
    item = {
        "id": "P024", "collection": "poses", "kind": "pose",
        "name": {"zh": "抱膝坐", "en": "Knees to chest"},
        "tags": ["坐", "抱膝"], "thumbnail": "https://example.test/thumb.jpg",
        "views": [{"role": "front", "thumbnail": "https://example.test/thumb.jpg",
                   "original": "https://example.test/full.png"}],
        "nsfw": False,
        "provenance": {"author": "作者", "url": "https://example.test/poses", "license": "仅供创作,禁止再分发"},
    }
    seen: list[dict[str, Any]] = []

    def invoke(_db, _instance_id, _capability, payload, *, collect=None, **kwargs):
        import tempfile

        seen.append(payload)
        op = payload["op"]
        if op == "collections":
            return {"collections": [{"id": "poses", "kind": "pose", "name": {"zh": "姿势", "en": "Poses"},
                                     "count": 1, "filters": [{"key": "series", "label": "系列",
                                                              "values": [{"value": "sexy", "label": "性感"}]}]}]}
        if op == "search":
            return {"items": [item], "next_cursor": ""}
        if op == "item":
            return {"item": item}
        if op == "fetch":
            assert collect is not None
            with tempfile.TemporaryDirectory(prefix="ref-test-") as folder:
                root = Path(folder)
                (root / "item.png").write_bytes(_png())
                collect({"artifact": {"path": "item.png"}}, root)
            return {}
        raise AssertionError(op)

    monkeypatch.setattr(reference_library.tools, "invoke_host", invoke)
    return seen


def test_目录_搜索_条目都规整成界面形状(monkeypatch):
    _client, _ws, instance = _setup()
    _fake_tools(monkeypatch)
    with SessionLocal() as db:
        collections = reference_library.collections(db, instance)
        page = reference_library.search(db, instance, collection="poses", q="抱膝")
        detail = reference_library.item(db, instance, item_id="P024")
    assert collections[0]["kind"] == "pose" and collections[0]["count"] == 1
    assert page["items"][0]["name"]["zh"] == "抱膝坐"
    assert detail["provenance"]["license"].startswith("仅供")
    assert detail["views"][0]["role"] == "front"


def test_用一条_登记素材并写下来源_可选存成姿势资产(monkeypatch):
    client, ws, instance = _setup()
    _fake_tools(monkeypatch)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "tester"))
        only_media = reference_library.use(
            db, user, instance, workspace_id=ws, item_id="P024", collection="poses", save_entity=False,
        )
        saved = reference_library.use(
            db, user, instance, workspace_id=ws, item_id="P024", collection="poses", save_entity=True,
        )
        media = db.get(Asset, only_media["asset_id"])
        entity = db.get(Entity, saved["entity_id"])
        db.refresh(media)
        source = media.media_info["external_source"]
        assert source["item_id"] == "P024" and source["author"] == "作者"
        assert media.source == "reference_library"
        assert entity.kind == "pose" and entity.cover_asset_id == saved["asset_id"]
        from app.db.models import EntityReference
        refs = db.scalars(select(EntityReference).where(EntityReference.entity_id == entity.id)).all()
        assert [ref.asset_id for ref in refs] == [saved["asset_id"]]


def test_连接列表只列认领参考库且启用的连接(monkeypatch):
    client, _ws, _instance = _setup()
    rows = client.get("/api/reference-library/connections").json()
    assert [row["name"] for row in rows] == ["姿势图集"]
