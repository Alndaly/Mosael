"""3D 场景契约的后端一侧:跑 contracts/scene-3d-cases.json。

前端 `scene3d.parity.test.ts` 跑**同一份文件**。

为什么不共用一份实现:工作台要在浏览器里用 three.js 交互编辑(拖物体、实时看光影),后端要无头
渲白模参考图、还要把同一个场景写成发去 Blender 的 GLB。三个消费者、两种语言,几何却必须是同一个
——人物多高、墙有多厚、球是不是站在地上、运镜怎么缓动。此前这份一致性只靠 `meshes.py` 开头那句
「逐项对照前端 SceneViewport」,而注释拦不住任何东西:哪天谁改了一侧,参考图、成片和 Blender 里的
场景会各是各的,并且**没有任何测试会红**。

**改语义时**:先改语料,看着两侧一起红,再改两侧实现。反过来做,语料就成了实现的复读机。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.domain.scene_render.meshes import meshes_for
from app.domain.scene_render.raster import kelvin_rgb, sun_direction
from app.domain.scene_render.sampling import sample_camera, sample_object
from app.domain.scene_types import SceneObject, SceneShot

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "scene-3d-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _tolerance() -> float:
    return float(_load()["tolerance"])


def _object(spec: dict) -> SceneObject:
    return SceneObject.model_validate({"id": "x", "name": spec.get("kind", "x"), **spec})


def test_语料在_而且有内容() -> None:
    """找不到语料就静默跳过是最坏的结果 —— 两侧都「通过」,而契约根本没跑。"""
    assert _CONTRACT.is_file(), f"3D 场景契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "scene-3d" and isinstance(data["version"], int)
    assert data["geometry"] and data["aids"] and data["sampling"] and data["lighting"]


@pytest.mark.parametrize("case", _load()["geometry"], ids=[c["name"] for c in _load()["geometry"]])
def test_几何和工作台画的是同一个东西(case) -> None:
    meshes = meshes_for(_object(case["object"]))
    assert len(meshes) == case["parts"], case["why"]
    points = np.concatenate([mesh.vertices for mesh in meshes])
    assert points.min(axis=0) == pytest.approx(case["min"], abs=_tolerance()), case["why"]
    assert points.max(axis=0) == pytest.approx(case["max"], abs=_tolerance()), case["why"]


@pytest.mark.parametrize("case", _load()["aids"], ids=[c["name"] for c in _load()["aids"]])
def test_编辑辅助物不进画面(case) -> None:
    assert case["rendered"] is False, "语料里 rendered=true 的东西不该出现在这条测试里"
    assert meshes_for(_object(case["object"])) == [], case["why"]


def test_运镜的插值和工作台一致() -> None:
    case = _load()["sampling"]["camera"]
    camera = _object(case["object"])
    shot = SceneShot.model_validate({"id": "s", "camera_id": "x", **case["shot"]})
    for sample in case["samples"]:
        pose = sample_camera(camera, shot, sample["t"])
        assert pose.position == pytest.approx(sample["position"], abs=_tolerance()), case["why"]
        assert pose.target == pytest.approx(sample["target"], abs=_tolerance()), case["why"]
        assert pose.fov == pytest.approx(sample["fov"], abs=_tolerance()), case["why"]


def test_物体动画的插值和工作台一致() -> None:
    case = _load()["sampling"]["object"]
    obj = _object(case["object"])
    shot = SceneShot.model_validate({"id": "s", "camera_id": "c", **case["shot"]})
    for sample in case["samples"]:
        pose = sample_object(obj, shot, sample["t"])
        assert pose.position == pytest.approx(sample["position"], abs=_tolerance()), case["why"]
        assert pose.rotation == pytest.approx(sample["rotation"], abs=_tolerance()), case["why"]
        assert pose.scale == pytest.approx(sample["scale"], abs=_tolerance()), case["why"]


def test_光照换算和工作台一致() -> None:
    lighting = _load()["lighting"]
    for case in lighting["kelvin"]:
        assert kelvin_rgb(case["kelvin"]) == pytest.approx(case["rgb"], abs=_tolerance()), lighting["why"]
    for case in lighting["sun"]:
        direction = sun_direction(case["azimuth"], case["elevation"])
        assert direction == pytest.approx(case["direction"], abs=_tolerance()), lighting["why"]
