"""给一张图重新打光(ADR 0108):灯位的几个数怎么翻成打光指令、节点怎么交给生成。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.workflows.executors import relight
from app.domain.workflows.executors.relight import light_values, relight_instruction
from tests.util import fresh_client, seed_assets


def test_没写的用缺省_超出的夹到边上_方位按圈取余() -> None:
    assert light_values({}) == relight.DEFAULTS
    got = light_values({"light_azimuth": 450, "light_elevation": -5, "light_temperature": 99999,
                        "light_softness": "2", "light_intensity": "不是数"})
    assert got == {"light_azimuth": 90.0, "light_elevation": 0.0, "light_temperature": 12000.0,
                   "light_softness": 1.0, "light_intensity": 60.0}


def test_灯位翻成一段打光指令_先说只改光_再说方向高度软硬色温亮度() -> None:
    text = relight_instruction({"light_azimuth": 268, "light_elevation": 8, "light_temperature": 3150,
                                "light_softness": 0.1, "light_intensity": 20}, "zh-CN")
    assert text.startswith("给这张图重新打光。")
    for part in ("画面左侧", "高度与视线齐平", "硬光", "3200K", "暖色(白炽灯)", "整体偏暗"):
        assert part in text, part
    #: 359° 离 0° 最近:是从镜头这边打的顺光,不是左前方。
    assert "正面" in relight_instruction({"light_azimuth": 359}, "zh-CN")
    assert "directly behind the subject" in relight_instruction({"light_azimuth": 180, "light_elevation": 85}, "en")


def test_补的那句接在指令后面_空着就不接() -> None:
    assert relight_instruction({"prompt": "  霓虹灯  "}, "zh-CN").endswith("光的感觉:霓虹灯")
    assert "光的感觉" not in relight_instruction({"prompt": "  "}, "zh-CN")


class _Stop(Exception):
    """提交到生成漏斗那一刻停下:要看的是交出去的是什么,不真的跑一次生成。"""


def test_原图以参考图交出去_要的画幅是原图的宽高(monkeypatch) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"photo": "image"})
    with SessionLocal() as db:
        db.get(Asset, "photo").media_info = {"width": 1280, "height": 720}
        db.commit()

    sent: dict[str, Any] = {}
    model = {"provider": "vendor", "provider_profile_id": "p1", "model": "edit-1"}
    monkeypatch.setattr(relight, "reference_model", lambda _db, choice, _actor: {**model, "choice": choice})
    monkeypatch.setattr(relight, "current_actor", lambda _db: None)

    def capture(_db: Any, **kwargs: Any) -> Any:
        sent.update(kwargs)
        raise _Stop

    monkeypatch.setattr(relight.generation_operations, "create_generation_job", capture)
    scope = SimpleNamespace(workspace_id=ws, id="board-1", name="画板")
    with SessionLocal() as db, pytest.raises(_Stop):
        relight.image_relight(db, scope, {"asset_id": "photo", "light_azimuth": 90, "prompt": "窗光"})

    assert sent["source_assets"] == [{"asset_id": "photo", "role": "reference_image"}]
    assert sent["frame_aspect"] == "1280x720"
    assert (sent["provider"], sent["provider_profile_id"], sent["model"], sent["kind"]) == ("vendor", "p1", "edit-1", "image")
    assert "画面右侧" in sent["prompt"] and sent["prompt"].endswith("窗光")


def test_别的工作区的图不收(monkeypatch) -> None:
    from app.core.db import SessionLocal
    from app.domain.workflows.errors import WorkflowDomainError

    client = fresh_client()
    mine = client.post("/api/workspaces", json={"name": "A"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "B"}).json()["id"]
    seed_assets(other, {"theirs": "image"})
    monkeypatch.setattr(relight, "current_actor", lambda _db: None)
    with SessionLocal() as db, pytest.raises(WorkflowDomainError) as caught:
        relight.image_relight(db, SimpleNamespace(workspace_id=mine, id="b", name="b"), {"asset_id": "theirs"})
    assert caught.value.key == "wfErr_assetNotInWorkspace"


def test_局部重绘那种必须再给蒙版的模型不算_只给参考图跑不起来() -> None:
    from app.domain.workflows.executors.reference_models import automatic_reference_model, works_from_reference_images

    caps = {"parameter_keys": ["reference_image", "mask"], "source_limits": {"reference_image": 1, "mask": 1}}
    inpaint = {"id": "inpaint", "adapter_available": True, "is_default": True,
               "capabilities": {**caps, "requires_source": [["mask"]]}}
    editor = {"id": "edit", "adapter_available": True, "capabilities": {**caps, "requires_source": [["reference_image"]]}}
    assert not works_from_reference_images(inpaint)
    assert works_from_reference_images(editor)
    assert automatic_reference_model([inpaint, editor]) is editor
