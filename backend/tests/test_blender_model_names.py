"""从 Blender 接回来的模型按场景起名:它们归工作区、道具的 3D 模型下拉里也列着,一排「Blender model」分不出是哪个。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_blender_models_are_named_after_their_scene
from app.db.models import Scene3D, Scene3DModel
from app.domain.blender.bridge import blender_model_name
from tests.util import fresh_client


def test_接回来的模型叫_场景名_Blender_不叠两遍() -> None:
    assert blender_model_name("老街夜景") == "老街夜景 · Blender"
    assert blender_model_name("老街夜景 · Blender") == "老街夜景 · Blender", "接回成新场景时场景名已经带着后缀"
    assert blender_model_name("  ") == "Blender"


def test_老的同名模型改成用它的那个场景_没人用的按编号() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        for model_id in ("m-used", "m-copy", "m-free-1", "m-free-2", "m-mine"):
            name = "我的椅子" if model_id == "m-mine" else "Blender model"
            db.add(Scene3DModel(id=model_id, workspace_id=ws, name=name, format="glb", file_key="", size=0))
        db.add(Scene3D(id="s1", workspace_id=ws, name="天台",
                       content={"objects": [{"id": "blender-model", "kind": "model", "model_id": "m-used"}]}))
        db.add(Scene3D(id="s2", workspace_id=ws, name="天台 · Blender",
                       content={"objects": [{"id": "blender-model", "kind": "model", "model_id": "m-copy"}]}))
        db.commit()

    _migrate_blender_models_are_named_after_their_scene()
    with SessionLocal() as db:
        names = {row.id: row.name for row in db.query(Scene3DModel).filter(Scene3DModel.workspace_id == ws)}
    assert names == {"m-used": "天台 · Blender", "m-copy": "天台 · Blender", "m-free-1": "Blender 1",
                     "m-free-2": "Blender 2", "m-mine": "我的椅子"}
