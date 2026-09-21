"""导入的模型能被白模渲染器画出来。

在这之前,`kind="model"` 的物体在后端**整个被跳过**:工作台(three.js)里看得见,而自动流程
渲给图像/视频模型的每一张参考帧里那件道具是空的 —— 两边都不报错,只是少了一块。于是
「在 Blender 里建模」那条链(inspect → execute → look → import)的产出,进不了自动成片的画面。

这里钉三件事:

1. **读得对** —— 写出去的那份 GLB 再读回来,几何和原来是同一个东西(round trip)。写和读用的
   是同一套约定(Y 上、右手、节点矩阵按列),分成两份实现就会分岔,所以让它们互相对表。
2. **画得上** —— 场景里有模型时,它真的进了三角形;没给模型库时如实记一笔跳过。
3. **读不了的说清楚** —— 压缩网格、外部 .bin、超过面数预算,每一种都给一句人看得懂的话,
   而不是悄悄少画一件东西。
"""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from app.domain.scene_render import _triangles, _world_matrices, find_shot
from app.domain.scene_render.gltf import write_glb
from app.domain.scene_render.model_mesh import (
    TRIANGLE_BUDGET,
    ModelLibrary,
    UnsupportedModel,
    library_for,
    read_model,
)
from app.domain.scene_types import SceneContent

CAMERA = {"id": "cam", "kind": "camera", "position": [0, 1.6, 6], "target": [0, 1, 0], "fov": 45}


def _scene(objects: list[dict]) -> SceneContent:
    return SceneContent.model_validate({
        "objects": [*objects, CAMERA],
        "shots": [{"id": "s", "camera_id": "cam", "duration": 4}],
    })


def _glb(tmp_path: Path, objects: list[dict], name: str = "model.glb") -> Path:
    """用后端自己的写入器造一份 GLB —— 读和写对表。"""
    content = _scene(objects)
    target = tmp_path / name
    write_glb(content, find_shot(content, "s"), target)
    return target


def _bounds(parts) -> tuple[np.ndarray, np.ndarray]:
    points = np.concatenate([part.vertices for part in parts])
    return points.min(axis=0), points.max(axis=0)


def test_写出去再读回来_几何还是同一个东西(tmp_path: Path) -> None:
    # 2×1×3 的箱子,底面贴地(meshes.box 的约定),摆在 x=4。
    path = _glb(tmp_path, [{"id": "b", "kind": "box", "position": [4, 0, 0],
                            "parameters": {"width": 2, "height": 1, "depth": 3}}])
    low, high = _bounds(read_model(path))
    assert np.allclose(low, [3, 0, -1.5], atol=1e-4), "位置和尺寸要原样回来"
    assert np.allclose(high, [5, 1, 1.5], atol=1e-4)


def test_节点层级乘进顶点_分组的位移不会丢(tmp_path: Path) -> None:
    """分组在 glTF 里是父节点。读的时候不把父矩阵乘下去,箱子就会回到原点。"""
    path = _glb(tmp_path, [
        {"id": "g", "kind": "group", "position": [10, 2, 0]},
        {"id": "b", "kind": "box", "parent_id": "g", "parameters": {"width": 1, "height": 1, "depth": 1}},
    ])
    low, high = _bounds(read_model(path))
    assert np.allclose((low + high) / 2, [10, 2.5, 0], atol=1e-4)


def test_每个图元跟自己的材质颜色_不被物体那一个刷成一色(tmp_path: Path) -> None:
    """一份 GLB 里有多种材质。颜色跟着图元走,否则整件道具会变成一个颜色。"""
    path = _glb(tmp_path, [
        {"id": "a", "kind": "box", "color": "#ff0000", "position": [-2, 0, 0]},
        {"id": "b", "kind": "box", "color": "#0000ff", "position": [2, 0, 0]},
    ])
    colors = [part.color for part in read_model(path)]
    assert all(color is not None for color in colors), "读出来的图元要带自己的基色"
    reds = [float(color[0]) for color in colors]
    assert max(reds) > 0.9 and min(reds) < 0.01, f"红的那个和蓝的那个要分得开:{reds}"


def test_场景里的模型真的进了三角形_没给库时如实记一笔跳过(tmp_path: Path) -> None:
    path = _glb(tmp_path, [{"id": "b", "kind": "box", "parameters": {"width": 2, "height": 2, "depth": 2}}])
    content = _scene([{"id": "prop", "kind": "model", "model_id": "m1", "position": [0, 0, 0]}])
    world = _world_matrices(content, find_shot(content, "s"), 0)

    bare, skipped = _triangles(content, world)
    assert len(bare.corners) == 0 and skipped == 1, "没有模型库时,少画的那件要报出来"

    drawn, skipped = _triangles(content, world, library_for({"m1": path}))
    assert len(drawn.corners) == 12 and skipped == 0, "给了库就该画上,而且不再算跳过"


def test_模型的姿态跟着场景走_不是钉在原点(tmp_path: Path) -> None:
    path = _glb(tmp_path, [{"id": "b", "kind": "box", "parameters": {"width": 1, "height": 1, "depth": 1}}])
    content = _scene([{"id": "prop", "kind": "model", "model_id": "m1", "position": [7, 0, 0],
                       "scale": [2, 2, 2]}])
    tris, _ = _triangles(content, _world_matrices(content, find_shot(content, "s"), 0),
                         library_for({"m1": path}))
    points = tris.corners.reshape(-1, 3)
    assert np.allclose(points.min(axis=0), [6, 0, -1], atol=1e-4), "位移和缩放都要作用上去"
    assert np.allclose(points.max(axis=0), [8, 2, 1], atol=1e-4)


def test_一份读不了不连累别的(tmp_path: Path) -> None:
    good = _glb(tmp_path, [{"id": "b", "kind": "box"}], "good.glb")
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"glTF\x02\x00\x00\x00")  # 头对、没有 JSON 块
    library = library_for({"ok": good, "broken": bad})
    assert library.get("ok"), "好的那份照读"
    assert "broken" in library.failures and not library.get("broken")


def _patched(path: Path, change) -> Path:
    """改一份 GLB 的 JSON 块,重写成新文件 —— 用来造那些正常导出不出来的坏情况。"""
    raw = path.read_bytes()
    length, _ = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length].decode())
    change(document)
    payload = json.dumps(document, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    rest = raw[20 + length:]
    target = path.with_name("patched.glb")
    target.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload) + len(rest))
                       + struct.pack("<II", len(payload), 0x4E4F534A) + payload + rest)
    return target


def test_压缩网格不假装能读_而且说清楚回_blender_怎么改(tmp_path: Path) -> None:
    path = _glb(tmp_path, [{"id": "b", "kind": "box"}])
    compressed = _patched(path, lambda doc: doc.update(extensionsRequired=["KHR_draco_mesh_compression"]))
    with pytest.raises(UnsupportedModel, match="Draco"):
        read_model(compressed)


def test_数据在旁边那个文件里时_说出来是哪一个(tmp_path: Path) -> None:
    """自包含才收得下:导入时只搬了一个文件,`scene.bin` 不在旁边。"""
    path = _glb(tmp_path, [{"id": "b", "kind": "box"}])
    external = _patched(path, lambda doc: doc["buffers"][0].update(uri="scene.bin"))
    with pytest.raises(UnsupportedModel, match="scene.bin"):
        read_model(external)


def test_面数超预算的拒绝掉_而不是把渲染挂在那里(tmp_path: Path) -> None:
    """光栅器是逐三角形的循环,一份几十万面的模型会让一次导出看起来像卡死了。"""
    path = _glb(tmp_path, [{"id": "b", "kind": "box"}])
    heavy = _patched(path, lambda doc: doc["accessors"][0].update(count=TRIANGLE_BUDGET * 3 + 3))
    with pytest.raises(UnsupportedModel, match="三角形"):
        read_model(heavy)


def test_内嵌_gltf_也读得了(tmp_path: Path) -> None:
    """导入支持两种格式(见 scenes._peek_format),读的这一侧不能只认其中一种。"""
    path = _glb(tmp_path, [{"id": "b", "kind": "box", "parameters": {"width": 2, "height": 2, "depth": 2}}])
    raw = path.read_bytes()
    length, _ = struct.unpack_from("<II", raw, 12)
    document = json.loads(raw[20:20 + length].decode())
    blob_length, _ = struct.unpack_from("<II", raw, 20 + length)
    blob = raw[28 + length:28 + length + blob_length]
    document["buffers"][0]["uri"] = "data:application/octet-stream;base64," + base64.b64encode(blob).decode()
    embedded = tmp_path / "model.gltf"
    embedded.write_text(json.dumps(document))
    low, high = _bounds(read_model(embedded))
    assert np.allclose(high - low, [2, 2, 2], atol=1e-4)


def test_空库就是空库_不会把没模型的场景弄坏() -> None:
    content = _scene([{"id": "b", "kind": "box"}])
    tris, skipped = _triangles(content, _world_matrices(content, find_shot(content, "s"), 0), ModelLibrary())
    assert len(tris.corners) == 12 and skipped == 0
