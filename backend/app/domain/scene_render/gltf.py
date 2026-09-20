"""场景 → GLB。**在后端写**,和白模渲染器同一份几何。

为什么要有这一份:把场景发到 Blender 此前只有一条路 —— 浏览器用 three.js 把当前视口导成 GLB
再上传。那条路要求有人正开着那个页面,于是智能体(跑在后端)根本发不了场景,只能在 Blender 里
从头建。现在发送收口到这里:界面上的按钮和智能体调的工具走同一个实现,同一份几何
(`meshes.meshes_for`,和渲染器、和工作台的 three.js 一一对照)。

导出的是**基本体**:每个物体一个节点,分组保持父子关系,颜色/粗糙度/金属度进 PBR 材质,
点光源用 KHR_lights_punctual。导入的 GLB 模型不在这里 —— 它们是独立的文件,由 Blender 那边
各自导入再挂到同名节点上(见 blender/worker.py 的 send),不必把别人的压缩网格解开再编一遍。

坐标系和 three.js / glTF 一致(Y 上、右手),所以物体矩阵原样写进节点,不做任何轴变换。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from app.domain.scene_render.meshes import meshes_for
from app.domain.scene_render.raster import hex_to_linear
from app.domain.scene_types import SceneContent, SceneObject, SceneShot

#: 这些 kind 不产生几何,但仍然是场景树上的节点:分组带着孩子走,模型是给 Blender 挂文件的锚,
#: 灯是光源。相机不写进 GLB —— 镜头由 worker 按 shots 另建(它要带上 Mosael 的目标距离)。
STRUCTURAL = {"group", "model", "light"}

#: 一个物体的自定义属性,导入两边都认得出它是谁。glTF 的 extras 在 Blender 里就是自定义属性。
EXTRA_ID = "mosael_object_id"
EXTRA_MODEL = "mosael_model_id"


def _pose_matrix(obj: SceneObject, shot: SceneShot, time: float) -> np.ndarray:
    from app.domain.scene_render import _local_matrix
    from app.domain.scene_render.sampling import sample_object

    pose = sample_object(obj, shot, time)
    return _local_matrix(pose.position, pose.rotation, pose.scale)


def _triangles(mesh) -> tuple[np.ndarray, np.ndarray]:
    """摊平成一串三角形:每个面三个独立顶点 + 面法线(平直着色,和白模渲染器看到的一样)。

    不建索引缓冲:基本体的面数很少,省下的那点字节不值得为它多写一套访问器 —— glTF 允许
    没有 indices 的图元。
    """
    corners = mesh.vertices[mesh.faces]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = np.divide(normals, np.where(lengths == 0, 1, lengths))
    return (corners.reshape(-1, 3).astype(np.float32),
            np.repeat(normals, 3, axis=0).astype(np.float32))


class _Builder:
    def __init__(self) -> None:
        self.blob = bytearray()
        self.views: list[dict[str, Any]] = []
        self.accessors: list[dict[str, Any]] = []

    def vec3(self, values: np.ndarray) -> int:
        data = np.ascontiguousarray(values, dtype=np.float32).tobytes()
        self.blob.extend(b"\x00" * (-len(self.blob) % 4))
        self.views.append({"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(data), "target": 34962})
        self.blob.extend(data)
        self.accessors.append({
            "bufferView": len(self.views) - 1, "componentType": 5126, "count": int(len(values)), "type": "VEC3",
            "min": [float(v) for v in values.min(axis=0)], "max": [float(v) for v in values.max(axis=0)],
        })
        return len(self.accessors) - 1


def scene_document(content: SceneContent, shot: SceneShot, time: float = 0.0) -> tuple[dict[str, Any], bytes]:
    """→ (glTF JSON, 二进制块)。导入的模型不在里面,由调用方按 `models` 单独交给 Blender。"""
    builder = _Builder()
    meshes: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    lights: list[dict[str, Any]] = []
    index_of: dict[str, int] = {}

    from app.domain.scene_render import _visible

    # 隐藏的不导出,**连同它的后代** —— 只看自己那一位的话,藏起来的分组里的东西会掉出来变成根节点。
    catalogue = {obj.id: obj for obj in content.objects}
    drawable = [obj for obj in content.objects if obj.kind != "camera" and _visible(obj, catalogue)]
    for obj in drawable:
        node: dict[str, Any] = {"name": obj.name or obj.id, "extras": {EXTRA_ID: obj.id}}
        # glTF 的矩阵是**按列**排的;我们的是按行,所以转置之后再摊平。
        node["matrix"] = [float(v) for v in _pose_matrix(obj, shot, time).T.flatten()]
        parts = meshes_for(obj)
        if parts:
            color = hex_to_linear(obj.color)
            materials.append({
                "name": f"{obj.name or obj.id} 材质",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [float(color[0]), float(color[1]), float(color[2]), 1.0],
                    "metallicFactor": float(obj.metalness), "roughnessFactor": float(obj.roughness),
                },
                "doubleSided": True,
            })
            primitives = []
            for part in parts:
                positions, normals = _triangles(part)
                primitives.append({"attributes": {"POSITION": builder.vec3(positions),
                                                  "NORMAL": builder.vec3(normals)},
                                   "material": len(materials) - 1})
            meshes.append({"name": obj.name or obj.id, "primitives": primitives})
            node["mesh"] = len(meshes) - 1
        elif obj.kind == "light":
            color = hex_to_linear(obj.color)
            lights.append({"type": "point", "color": [float(color[0]), float(color[1]), float(color[2])],
                           "intensity": float(obj.intensity) * 1000})
            node["extensions"] = {"KHR_lights_punctual": {"light": len(lights) - 1}}
        elif obj.kind == "model":
            # 模型文件由 Blender 那边导入并挂到这个空节点下 —— 这里只占个位置和姿态。
            node["extras"][EXTRA_MODEL] = obj.model_id or ""
        nodes.append(node)
        index_of[obj.id] = len(nodes) - 1

    roots = []
    for obj in drawable:
        parent = obj.parent_id
        if parent and parent in index_of:
            nodes[index_of[parent]].setdefault("children", []).append(index_of[obj.id])
        else:
            roots.append(index_of[obj.id])

    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "Mosael"},
        "scene": 0,
        "scenes": [{"nodes": roots}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": builder.accessors,
        "bufferViews": builder.views,
        "buffers": [{"byteLength": len(builder.blob)}],
    }
    if lights:
        document["extensionsUsed"] = ["KHR_lights_punctual"]
        document["extensions"] = {"KHR_lights_punctual": {"lights": lights}}
    return document, bytes(builder.blob)


def write_glb(content: SceneContent, shot: SceneShot, target: Path, time: float = 0.0) -> dict[str, Any]:
    """把场景写成一个自包含的 GLB。返回写了哪些物体、以及哪些导入模型要另外交给 Blender。"""
    document, blob = scene_document(content, shot, time)
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    blob += b"\x00" * (-len(blob) % 4)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        out.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload) + (8 + len(blob) if blob else 0)))
        out.write(struct.pack("<II", len(payload), 0x4E4F534A))
        out.write(payload)
        if blob:
            out.write(struct.pack("<II", len(blob), 0x004E4942))
            out.write(blob)
    return {
        "objects": len(document["nodes"]),
        "models": [{"object_id": node["extras"][EXTRA_ID], "model_id": node["extras"][EXTRA_MODEL]}
                   for node in document["nodes"] if EXTRA_MODEL in node["extras"]],
    }
