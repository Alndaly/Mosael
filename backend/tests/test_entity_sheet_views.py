"""拼版参考图拆成单张视图(entities.sheet_views,ADR 0097 修订六)。

三视图横排三人、设计稿 2×2 四格:原样交给出图模型,它会把版式一起照搬,画出几宫格(《长明灯》第 2 场第 16 镜)。
同一镜、同一模型、三个种子:交拼版图三张全是拼图,拆成单图三张全是一整张。所以拆开挂回资产,画关键帧时只交单张视图。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Entity
from app.domain.assets.importer import register_file_asset
from app.domain.entities.library import add_reference, references_of
from app.domain.entities.sheet_views import attach_sheet_views
from app.domain.workflows.executors.entities import entity_get, entity_sheet_views
from tests.util import fresh_client, seed_assets

COLORS = ("red", "green", "blue", "yellow")


def _sheet(db, workspace_id: str, rows: int, cols: int):
    """一张真的拼版图:白底、细白分隔线,每格一种颜色(按阅读顺序 红 / 绿 / 蓝 / 黄)。"""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sheet.png"
        image = Image.new("RGB", (cols * 100, rows * 100), "white")
        for index in range(rows * cols):
            row, col = divmod(index, cols)
            image.paste(COLORS[index], (col * 100 + 4, row * 100 + 4, col * 100 + 96, row * 100 + 96))
        image.save(path)
        asset = register_file_asset(db, workspace_id=workspace_id, project_id=None, source_path=path,
                                    name="sheet.png", source="generated")
    db.flush()
    return asset


def _entity(client, ws: str, kind: str, name: str) -> str:
    made = client.post("/api/entities", json={"workspace_id": ws, "kind": kind, "name": name})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _centre_color(db, asset_id: str) -> tuple[int, int, int]:
    from app.db.models import Asset
    from app.media.paths import resolve_key

    with Image.open(resolve_key(db.get(Asset, asset_id).file_key)) as image:
        return image.convert("RGB").getpixel((image.width // 2, image.height // 2))


def test_三视图拆成正面_侧面_背面_按阅读顺序_去掉分隔线() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    entity_id = _entity(client, ws, "character", "小满")
    with SessionLocal() as db:
        entity = db.get(Entity, entity_id)
        sheet = _sheet(db, ws, 1, 3)
        add_reference(db, entity, sheet.id, "turnaround")
        views = attach_sheet_views(db, entity)
        roles = [(ref.role, asset.id) for ref, asset in references_of(db, entity_id)]
        assert [role for role, _ in roles] == ["turnaround", "front", "side", "back"]
        assert views == [asset_id for role, asset_id in roles if role != "turnaround"]
        assert [_centre_color(db, one) for one in views] == [(255, 0, 0), (0, 128, 0), (0, 0, 255)]
        db.commit()


def test_设计稿拆成俯视_反打_两张细节() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    entity_id = _entity(client, ws, "location", "灯铺")
    with SessionLocal() as db:
        entity = db.get(Entity, entity_id)
        add_reference(db, entity, _sheet(db, ws, 2, 2).id, "design_sheet")
        views = attach_sheet_views(db, entity)
        assert [ref.role for ref, _ in references_of(db, entity_id)] == [
            "design_sheet", "overhead", "reverse", "detail", "detail"]
        assert len(views) == 4
        db.commit()


def test_拆过的不再拆_只有正面照的人物照样交出那张正面照() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"photo": "image"})
    with_sheet = _entity(client, ws, "character", "小满")
    photo_only = _entity(client, ws, "character", "沈青禾")
    with SessionLocal() as db:
        entity = db.get(Entity, with_sheet)
        add_reference(db, entity, _sheet(db, ws, 1, 3).id, "turnaround")
        first = attach_sheet_views(db, entity)
        again = attach_sheet_views(db, entity)
        assert again == first and len(references_of(db, with_sheet)) == 4, "同一张三视图只切一次"
        add_reference(db, db.get(Entity, photo_only), "photo", "front")
        assert attach_sheet_views(db, db.get(Entity, photo_only)) == ["photo"]
        db.commit()


def test_节点按名字认资产拆开_取资产只要单张视图时不交拼版图() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    entity_id = _entity(client, ws, "character", "小满")
    scope = SimpleNamespace(workspace_id=ws, id="wf", name="测试流程")
    with SessionLocal() as db:
        sheet = _sheet(db, ws, 1, 3)
        add_reference(db, db.get(Entity, entity_id), sheet.id, "turnaround")
        out = entity_sheet_views(db, scope, {"kind": "character", "name": "小满"})
        assert out["entity_id"] == entity_id and out["count"] == 3
        got = entity_get(db, scope, {"kind": "character", "name": "小满", "views": "yes", "limit": 3})
        assert got["asset_ids"] == out["asset_ids"] and sheet.id not in got["asset_ids"]
        missing = entity_sheet_views(db, scope, {"kind": "character", "name": "没有这个人"})
        assert missing == {"entity_id": "", "asset_ids": [], "count": 0}, "这一轮没画成的角色不是错"
        db.commit()
