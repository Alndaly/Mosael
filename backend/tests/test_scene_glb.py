"""场景 → GLB,在后端生成。

它存在的理由是「发送到 Blender」不再要求有人开着浏览器:界面按钮和智能体的 blender_send_scene
走同一个实现。所以这里钉的是**交出去的那份文件描述的就是这个场景**:该在的物体在、藏起来的
连同后代一起不在、分组的父子关系还在、姿态按 glTF 的列主序写、导入的模型留着锚点等 Blender
那边挂文件。几何本身与白模渲染器同源(meshes.meshes_for),由 test_scene_render.py 盯着。
"""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from app.domain.scenes import glb
from app.domain.scenes.render import find_shot
from app.domain.scenes.render.gltf import EXTRA_ID, EXTRA_MODEL, scene_document, write_glb
from app.domain.scenes.types import SceneContent

CAMERA = {"id": "cam", "kind": "camera", "position": [0, 1.6, 6], "target": [0, 1, 0], "fov": 45}


def _scene(objects: list[dict]) -> SceneContent:
    return SceneContent.model_validate({
        "objects": [*objects, CAMERA],
        "shots": [{"id": "s", "camera_id": "cam", "duration": 4}],
    })


def _document(objects: list[dict], time: float = 0.0) -> dict:
    content = _scene(objects)
    return scene_document(content, find_shot(content, "s"), time)[0]


def _by_id(document: dict) -> dict[str, dict]:
    return {node["extras"][EXTRA_ID]: node for node in document["nodes"]}


def test_分组的父子关系原样带过去() -> None:
    document = _document([
        {"id": "g", "kind": "group", "name": "展厅", "position": [3, 0, 0]},
        {"id": "b", "kind": "box", "name": "箱子", "parent_id": "g"},
    ])
    nodes, index = document["nodes"], _by_id(document)
    assert document["scenes"][0]["nodes"] == [nodes.index(index["g"])], "只有分组是根节点"
    assert index["g"]["children"] == [nodes.index(index["b"])]


def test_藏起来的分组连同后代一起不导出() -> None:
    """只看自己那一位的话,藏起来的分组里的东西会掉出来、变成画面里凭空出现的根节点。"""
    document = _document([
        {"id": "g", "kind": "group", "hidden": True},
        {"id": "b", "kind": "box", "parent_id": "g"},
        {"id": "keep", "kind": "box"},
    ])
    assert list(_by_id(document)) == ["keep"]


def test_相机不进_GLB_镜头由_worker_另建() -> None:
    assert "cam" not in _by_id(_document([{"id": "b", "kind": "box"}]))


def test_姿态按_glTF_的列主序写() -> None:
    """写成行主序的话,平移会跑到矩阵的最后一行 —— Blender 里所有东西都堆在原点。"""
    matrix = _by_id(_document([{"id": "b", "kind": "box", "position": [1, 2, 3]}]))["b"]["matrix"]
    assert matrix[12:] == [1.0, 2.0, 3.0, 1.0]


def test_动画物体导出的是那一刻的姿态() -> None:
    moving = {"id": "b", "kind": "box", "track": [
        {"time": 0, "position": [0, 0, 0]}, {"time": 4, "position": [4, 0, 0]}]}
    assert _document([moving], time=4)["nodes"][0]["matrix"][12] == 4.0


def test_颜色_粗糙度_金属度进_PBR_材质() -> None:
    document = _document([{"id": "b", "kind": "box", "color": "#ff0000", "roughness": 0.3, "metalness": 0.8}])
    pbr = document["materials"][0]["pbrMetallicRoughness"]
    assert pbr["roughnessFactor"] == 0.3 and pbr["metallicFactor"] == 0.8
    # sRGB 的 #ff0000 在 glTF 里是线性的 1,0,0;不转换的话所有颜色在 Blender 里都偏亮。
    assert pbr["baseColorFactor"] == [1.0, 0.0, 0.0, 1.0]
    dark = _document([{"id": "b", "kind": "box", "color": "#808080"}])["materials"][0]
    assert 0.21 < dark["pbrMetallicRoughness"]["baseColorFactor"][0] < 0.22


def test_导入的模型只留锚点_文件另外交给_Blender(tmp_path) -> None:
    content = _scene([{"id": "m", "kind": "model", "name": "凉亭", "model_id": "mdl-1", "position": [2, 0, 0]}])
    written = write_glb(content, find_shot(content, "s"), tmp_path / "scene.glb")
    assert written["models"] == [{"object_id": "m", "model_id": "mdl-1"}]
    document = json.loads(Path(tmp_path / "scene.glb").read_bytes()[20:].split(b"\x00", 1)[0].rstrip() or b"{}") \
        if False else scene_document(content, find_shot(content, "s"))[0]
    anchor = _by_id(document)["m"]
    assert "mesh" not in anchor and anchor["extras"][EXTRA_MODEL] == "mdl-1"


def test_点光源带着颜色和强度过去() -> None:
    document = _document([{"id": "l", "kind": "light", "color": "#ffffff", "intensity": 2}])
    assert document["extensionsUsed"] == ["KHR_lights_punctual"]
    assert document["extensions"]["KHR_lights_punctual"]["lights"][0]["type"] == "point"
    assert _by_id(document)["l"]["extensions"]["KHR_lights_punctual"]["light"] == 0


def test_写出来的是一个能被认出来的_GLB(tmp_path) -> None:
    content = _scene([{"id": "r", "kind": "room"}])
    target = tmp_path / "scene.glb"
    write_glb(content, find_shot(content, "s"), target)
    raw = target.read_bytes()
    magic, version, length = struct.unpack("<4sII", raw[:12])
    assert magic == b"glTF" and version == 2 and length == len(raw), "长度写错的文件多数解析器直接拒"
    json_length, json_type = struct.unpack("<II", raw[12:20])
    assert json_type == 0x4E4F534A and json.loads(raw[20:20 + json_length])["asset"]["version"] == "2.0"

    from app.domain.scenes.operations import validate_model_file

    assert validate_model_file(target) == "glb"


def test_顶点是三角形摊平的_法线跟着面走() -> None:
    document, blob = scene_document(*(lambda c: (c, find_shot(c, "s")))(_scene([{"id": "b", "kind": "box"}])))
    positions, normals = document["accessors"][0], document["accessors"][1]
    assert positions["count"] == normals["count"] == 12 * 3, "立方体 12 个三角形,每个三顶点"
    view = document["bufferViews"][normals["bufferView"]]
    values = np.frombuffer(blob[view["byteOffset"]:view["byteOffset"] + view["byteLength"]], dtype=np.float32)
    assert np.allclose(np.linalg.norm(values.reshape(-1, 3), axis=1), 1), "法线要是单位向量"


# ---------------- GLB 容器格式只有一份(domain/scenes/glb)----------------
# 导入校验(只读头和 JSON 块)与渲染读取(整份读)此前各写一遍,对「头里声明的长度」口径不同。


def _glb_bytes(tmp_path, document: dict, blob: bytes = b"") -> bytes:
    path = tmp_path / "x.glb"
    glb.write(path, document, blob)
    return path.read_bytes()


def test_写出去的_GLB_两种读法都读得回来(tmp_path) -> None:
    document = {"asset": {"version": "2.0"}, "nodes": [{"name": "方块"}]}
    raw = _glb_bytes(tmp_path, document, b"\x01\x02\x03")
    assert glb.is_glb(raw) and len(raw) % 4 == 0
    read_back, blob = glb.read(raw)
    assert read_back == document and blob.rstrip(b"\x00") == b"\x01\x02\x03"
    assert glb.read_document(io.BytesIO(raw), len(raw)) == document
    assert glb.read(_glb_bytes(tmp_path, document))[1] is None  # 空的二进制块不写


def test_坏的_GLB_两种读法给同样的判断(tmp_path) -> None:
    raw = _glb_bytes(tmp_path, {"asset": {"version": "2.0"}}, b"\x00" * 8)
    cases = {
        "layout": raw + b"\x00\x00\x00\x00",  # 头里声明的总长和文件对不上
        "version": raw[:4] + struct.pack("<I", 1) + raw[8:],
    }
    for reason, broken in cases.items():
        with pytest.raises(glb.GlbError) as whole:
            glb.read(broken)
        with pytest.raises(glb.GlbError) as head_only:
            glb.read_document(io.BytesIO(broken), len(broken))
        assert whole.value.reason == head_only.value.reason == reason
    only_bin = struct.pack("<4sII", b"glTF", 2, 12 + 8 + 4) + struct.pack("<II", 4, glb.BIN_CHUNK) + b"\x00" * 4
    with pytest.raises(glb.GlbError) as no_json:
        glb.read(only_bin)
    assert no_json.value.reason == "no_json"
