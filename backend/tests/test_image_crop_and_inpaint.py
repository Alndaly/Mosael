"""图片格上的裁切与局部重绘(ADR 0110):框是比例、本机切;重绘挑模型、交什么、结果怎么贴回原图。"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from app.domain.assets.image_crop import CropBox
from app.domain.assets.inpaint_composite import composite
from app.domain.workflows.executors import image_edit
from app.domain.workflows.executors.image_edit import crop_box
from app.domain.workflows.executors.reference_models import (
    automatic_inpaint_model,
    inpaint_candidates,
    works_for_inpaint,
)
from tests.util import fresh_client


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _import(client: Any, workspace_id: str, name: str, image: Image.Image) -> str:
    made = client.post("/api/assets/import", data={"workspace_id": workspace_id},
                       files={"file": (name, _png(image), "image/png")})
    assert made.status_code in (200, 201), made.text
    return made.json()["id"]


# ---- 裁切 ----


def test_框没写的按整张_写错的按整张_超出的夹进图里() -> None:
    assert crop_box({}) == CropBox.whole()
    assert crop_box({"crop_x": "不是数", "crop_width": None}) == CropBox.whole()
    box = CropBox(0.8, -0.2, 0.5, 2.0).clamped()
    assert (box.x, box.y, box.width, box.height) == (0.8, 0.0, pytest.approx(0.2), 1.0)
    assert CropBox(0.25, 0.5, 0.5, 0.5).pixels(200, 100) == (50, 50, 150, 100)


def test_按比例切出一块进素材库_记着出处_原图不变() -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset
    from app.media.paths import resolve_key

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    picture = Image.new("RGB", (200, 100), "red")
    picture.paste(Image.new("RGB", (100, 50), "blue"), (100, 50))
    source_id = _import(client, ws, "photo.png", picture)
    scope = SimpleNamespace(workspace_id=ws, id="board-1", name="画板")
    with SessionLocal() as db:
        out = image_edit.image_crop(db, scope, {"asset_id": source_id, "crop_x": 0.5, "crop_y": 0.5,
                                                "crop_width": 0.5, "crop_height": 0.5})
        assert out["source_asset_id"] == source_id
        piece = db.get(Asset, out["asset_id"])
        assert piece.derived_from == [{"asset_id": source_id, "op": "crop"}]
        with Image.open(resolve_key(piece.file_key)) as cut:
            assert cut.size == (100, 50) and cut.convert("RGB").getpixel((50, 25)) == (0, 0, 255)
        with Image.open(resolve_key(db.get(Asset, source_id).file_key)) as original:
            assert original.size == (200, 100)


def test_框得太小的说清楚() -> None:
    from app.core.db import SessionLocal
    from app.domain.workflows.errors import WorkflowDomainError

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source_id = _import(client, ws, "photo.png", Image.new("RGB", (100, 100), "red"))
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        image_edit.image_crop(db, SimpleNamespace(workspace_id=ws, id="b", name="b"),
                              {"asset_id": source_id, "crop_width": 0.1, "crop_height": 0.1})
    assert caught.value.key == "cropErr_tooSmall"


# ---- 重绘:挑模型 ----


def _option(option_id: str, *, refs: int = 1, mask: bool = False, requires: list[list[str]] | None = None,
            default: bool = False, available: bool = True) -> dict[str, Any]:
    keys = ["reference_image"] + (["mask"] if mask else [])
    limits = {"reference_image": refs, **({"mask": 1} if mask else {})}
    return {"id": option_id, "adapter_available": available, "is_default": default,
            "capabilities": {"parameter_keys": keys if refs else (["mask"] if mask else []),
                             "source_limits": limits if refs else {}, "requires_source": requires or []}}


def test_重绘能用收参考图的_收蒙版的排前面_必须给蒙版的也算() -> None:
    editor = _option("edit", refs=4)
    inpaint = _option("inpaint", mask=True, requires=[["mask"]])
    text_only = _option("t2i", refs=0)
    needs_video = _option("odd", refs=1, requires=[["first_frame"]])
    offline = _option("off", refs=2, available=False)
    assert works_for_inpaint(inpaint) and works_for_inpaint(editor)
    assert not any(works_for_inpaint(one) for one in (text_only, needs_video, offline))
    assert [one["id"] for one in inpaint_candidates([text_only, editor, inpaint, offline])] == ["inpaint", "edit"]


def test_没点名时_够格的默认优先_否则第一个收蒙版的() -> None:
    editor = _option("edit", refs=4, default=True)
    inpaint = _option("inpaint", mask=True)
    assert automatic_inpaint_model([inpaint, editor]) is editor
    assert automatic_inpaint_model([_option("edit", refs=4), inpaint]) is inpaint
    assert automatic_inpaint_model([_option("t2i", refs=0)]) is None


# ---- 重绘:交什么 ----


class _Stop(Exception):
    """提交到生成漏斗那一刻停下:要看的是交出去的是什么,不真的跑一次生成。"""


def _capture(monkeypatch: Any, model: dict[str, Any]) -> dict[str, Any]:
    from app.domain.workflows.executors import subjobs

    sent: dict[str, Any] = {}
    monkeypatch.setattr(image_edit, "inpaint_model", lambda _db, _choice, _actor: model)
    monkeypatch.setattr(image_edit, "current_actor", lambda _db: None)
    monkeypatch.setattr(subjobs, "current_actor", lambda _db: None)

    def capture(_db: Any, **kwargs: Any) -> Any:
        sent.update(kwargs)
        raise _Stop

    monkeypatch.setattr(subjobs.generation_operations, "create_generation_job", capture)
    return sent


def _seeded() -> tuple[str, str, str]:
    from app.core.db import SessionLocal
    from app.db.models import Asset

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    photo = _import(client, ws, "photo.png", Image.new("RGB", (64, 32), "red"))
    mask = _import(client, ws, "mask.png", Image.new("L", (64, 32), 0))
    with SessionLocal() as db:
        db.get(Asset, photo).media_info = {**(db.get(Asset, photo).media_info or {}), "width": 64, "height": 32}
        db.commit()
    return ws, photo, mask


@pytest.mark.parametrize(("model", "sources", "instructed"), [
    #: 收蒙版的:蒙版就以蒙版交出去,提示词就是那一句。
    (_option("inpaint", mask=True), ["reference_image", "mask"], False),
    #: 不收蒙版、收得下两张参考图的:蒙版是第二张参考图,提示词前面说清楚它是什么。
    (_option("edit", refs=4), ["reference_image", "reference_image"], True),
    #: 只收一张的:只给原图,改哪儿由贴回时的蒙版管。
    (_option("single", refs=1), ["reference_image"], False),
])
def test_按模型收什么交原图和蒙版_画幅是原图的宽高(monkeypatch, model, sources, instructed) -> None:
    from app.core.db import SessionLocal

    ws, photo, mask = _seeded()
    sent = _capture(monkeypatch, {**model, "provider": "vendor", "provider_profile_id": "p1", "model": model["id"]})
    with SessionLocal() as db, pytest.raises(_Stop):
        image_edit.image_inpaint(db, SimpleNamespace(workspace_id=ws, id="b", name="b"),
                                 {"asset_id": photo, "mask_asset_id": mask, "prompt": "换成红色的围巾"})
    assert [one["role"] for one in sent["source_assets"]] == sources
    assert sent["source_assets"][0]["asset_id"] == photo
    assert all(one["asset_id"] == mask for one in sent["source_assets"][1:])
    assert sent["frame_aspect"] == "64x32" and sent["kind"] == "image"
    assert sent["prompt"].endswith("换成红色的围巾")
    assert ("第二张图是蒙版" in sent["prompt"]) is instructed


@pytest.mark.parametrize(("config", "key"), [
    ({"prompt": "围巾"}, "wfErr_inpaintNoMask"),
    ({"mask_asset_id": "m"}, "wfErr_inpaintNoPrompt"),
])
def test_没画蒙版_没写改成什么_下单之前就说(monkeypatch, config, key) -> None:
    from app.core.db import SessionLocal
    from app.domain.workflows.errors import WorkflowDomainError

    ws, photo, _mask = _seeded()
    sent = _capture(monkeypatch, _option("edit", refs=4))
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        image_edit.image_inpaint(db, SimpleNamespace(workspace_id=ws, id="b", name="b"), {"asset_id": photo, **config})
    assert caught.value.key == key and not sent


# ---- 重绘:贴回原图 ----


def test_蒙版外逐像素是原图_蒙版里换成画出来的_尺寸跟着原图() -> None:
    original = Image.new("RGB", (200, 100), (200, 0, 0))
    painted = Image.new("RGB", (100, 50), (0, 0, 200))  # 模型交回的尺寸不一样:缩放到原图
    mask = Image.new("L", (200, 100), 0)
    mask.paste(255, (0, 0, 100, 100))
    merged = composite(original, painted, mask)
    assert merged.size == (200, 100)
    assert merged.getpixel((190, 50)) == (200, 0, 0), "蒙版外是原图"
    assert merged.getpixel((10, 50)) == (0, 0, 200), "蒙版里是画出来的"
    #: 边上羽化过:接缝处是两者之间的过渡,不是一刀切。
    seam = merged.getpixel((100, 50))
    assert 0 < seam[0] < 200 and 0 < seam[2] < 200


def test_跑完交回贴好的那张_模型交回的整张记成中间产物(monkeypatch) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset
    from app.domain.assets.importer import register_file_asset
    from app.domain.assets.intermediates import INPAINT_DRAFT
    from app.media.paths import resolve_key

    ws, photo, mask = _seeded()
    with SessionLocal() as db, tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "painted.png"
        Image.new("RGB", (64, 32), "blue").save(target)
        painted_id = register_file_asset(db, workspace_id=ws, project_id=None, source_path=target,
                                         name="painted", source="generated", ai_generated=True).id
        db.commit()
    monkeypatch.setattr(image_edit, "generate_one",
                        lambda _db, _scope, _config, _order: {"asset_id": painted_id, "asset_ids": [painted_id]})
    with SessionLocal() as db:
        out = image_edit.image_inpaint(db, SimpleNamespace(workspace_id=ws, id="b", name="b"),
                                       {"asset_id": photo, "mask_asset_id": mask, "prompt": "蓝色"})
        db.commit()
    with SessionLocal() as db:
        merged = db.get(Asset, out["asset_id"])
        assert out["asset_ids"] == [merged.id]
        assert merged.derived_from == [{"asset_id": photo, "op": "inpaint"}, {"asset_id": painted_id, "op": "inpaint"},
                                       {"asset_id": mask, "op": "inpaint"}]
        assert merged.ai_generated, "含 AI 由生成的那张继承"
        assert db.get(Asset, painted_id).intermediate == INPAINT_DRAFT
        #: 蒙版全黑:一个像素都不该换。
        with Image.open(resolve_key(merged.file_key)) as result:
            assert result.convert("RGB").getpixel((32, 16)) == (255, 0, 0)
