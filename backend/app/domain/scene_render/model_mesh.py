"""导入的模型(glTF / GLB)→ 白模渲染器认得的三角形。

## 为什么要有这一份

此前后端渲染器把 `kind="model"` 的物体**整个跳过**,只在 `skipped_models` 里记一个数。
于是在 Blender 里建好、收进 Mosael 的东西:工作台(three.js)里看得见,而后端渲出来的每一张
白模参考帧里**根本不存在** —— 自动流程送给图像/视频模型的构图参考里,那件道具是空的。

"看得见但渲不出"是最难认的一种:两边都没报错,只是少了一块。这一份把那块补上 ——
Blender 那条建模链(inspect → execute → look → import)的产出,从此能进自动成片的画面。

## 读哪些、不读哪些

只读**几何和基色**:白模要传的是形状、体积和光的结构,不是材质(见 raster.py 开头那段)。
贴图、动画、蒙皮、形态键一概不读 —— 读了也不画,白花时间。

压缩网格(Draco)和压缩贴图(KTX2)不解:解压要另外拉一个依赖,而它们**只影响能不能读**,
不影响这一层的约定。读不了就如实报出来(`ModelLibrary.failures`),不假装它在。

坐标系和 glTF 一致(Y 上、右手),与 `SceneContent` 同一套,所以顶点原样用,不做轴变换 ——
写出去那一份(gltf.py)也是这个约定,两边对称。

## 面数预算

光栅器是逐三角形的 Python 循环(raster._rasterize),实测约 26 µs/三角形(960×540)。
一份 40 万面的模型渲一帧要一分多钟,而运镜视频是七十多帧 —— 那不是"慢",是挂住。
所以有 `TRIANGLE_BUDGET`:超了的模型**不渲,并说清楚超了多少**,让人(或智能体)回 Blender
做一次精简再导入。悄悄渲下去比拒绝更糟:用户只会看到导出卡在那里,不知道为什么。
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.i18n import LocalizedError
from app.domain.scene_render.meshes import Mesh

#: 单份模型的面数上限。见模块开头那段:这是渲染时间的闸,不是格式限制。
TRIANGLE_BUDGET = 150_000

#: glTF 的 componentType → numpy 类型。
_COMPONENTS = {5120: "<i1", 5121: "<u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
#: glTF 的 type → 每个元素几个分量。
_COUNTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
#: 只画三角形。线、点、条带/扇形在白模里没有意义(没有面就没有体积),跳过不算错。
_TRIANGLES = 4

_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942


class UnsupportedModel(LocalizedError, ValueError):
    """这份模型读不了。消息是**给人看的**:说清楚是哪一种读不了,以及能怎么办。

    带文案 key(`modelMeshErr_*`),按读的人的语言翻。"""


@dataclass(frozen=True)
class ModelLibrary:
    """一个场景里所有导入模型的几何。

    渲染器拿它而不是拿数据库:`scene_render` 不认识 Scene3DModel,也不该认识 ——
    它只需要"这个 model_id 长什么样"。谁去磁盘上找文件由 domain/scenes 回答。

    一次装好、整段渲染共用:运镜视频要渲七十多帧,每帧重新解一遍 GLB 是七十多倍的无用功。
    """

    meshes: dict[str, list[Mesh]] = field(default_factory=dict)
    #: model_id → 读不了的原因(给人看的那句)。**空 dict 才是"都读到了"**。
    failures: dict[str, str] = field(default_factory=dict)

    def get(self, model_id: str | None) -> list[Mesh]:
        return self.meshes.get(model_id or "", [])


def library_for(files: dict[str, Path]) -> ModelLibrary:
    """把 {model_id: 文件路径} 读成一份库。**一份读不了不影响别的** —— 一件道具坏了,
    整个场景不该跟着变空。"""
    meshes: dict[str, list[Mesh]] = {}
    failures: dict[str, str] = {}
    for model_id, path in files.items():
        try:
            meshes[model_id] = read_model(path)
        except UnsupportedModel as exc:
            failures[model_id] = str(exc)
        except (OSError, ValueError, KeyError, IndexError, struct.error) as exc:
            failures[model_id] = str(UnsupportedModel("modelMeshErr_unreadable", detail=str(exc)))
    return ModelLibrary(meshes=meshes, failures=failures)


def read_model(path: Path) -> list[Mesh]:
    """一份 glTF/GLB → 模型自己坐标系下的几何(节点层级已经乘进顶点)。"""
    document, blob = _open(path)
    _refuse_compressed(document)
    buffers = _buffers(document, blob)
    parts: list[Mesh] = []
    total = 0
    for matrix, mesh_index in _nodes(document):
        for primitive in (document.get("meshes") or [])[mesh_index].get("primitives") or []:
            if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
                continue
            # 先按访问器上声明的数量算面数,**再决定读不读**:一份几百万面的模型,光是把它的
            # 顶点搬进内存就已经是伤害了,不该等读完了才说"太大"。
            total += _face_count(document, primitive)
            if total > TRIANGLE_BUDGET:
                raise UnsupportedModel("modelMeshErr_tooManyTriangles", limit=f"{TRIANGLE_BUDGET:,}")
            part = _primitive(document, buffers, primitive, matrix)
            if part is not None:
                parts.append(part)
    if not parts:
        raise UnsupportedModel("modelMeshErr_noMesh")
    return parts


def _open(path: Path) -> tuple[dict, bytes | None]:
    """→ (glTF 文档, GLB 的二进制块或 None)。"""
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        return json.loads(raw.decode("utf-8")), None
    _, version, _ = struct.unpack_from("<4sII", raw, 0)
    if version != 2:
        raise UnsupportedModel("modelMeshErr_gltfVersion", version=version)
    document: dict | None = None
    blob: bytes | None = None
    offset = 12
    while offset + 8 <= len(raw):
        length, kind = struct.unpack_from("<II", raw, offset)
        body = raw[offset + 8:offset + 8 + length]
        if kind == _JSON_CHUNK:
            document = json.loads(body.decode("utf-8"))
        elif kind == _BIN_CHUNK:
            blob = body
        offset += 8 + length
    if document is None:
        raise UnsupportedModel("modelMeshErr_glbNoJson")
    return document, blob


def _refuse_compressed(document: dict) -> None:
    """压缩网格不解 —— 说清楚是哪一种,以及回 Blender 怎么改。"""
    required = set(document.get("extensionsRequired") or [])
    if "KHR_draco_mesh_compression" in required:
        raise UnsupportedModel("modelMeshErr_draco")
    if "EXT_meshopt_compression" in required:
        raise UnsupportedModel("modelMeshErr_meshopt")


def _buffers(document: dict, blob: bytes | None) -> list[bytes]:
    """每个 buffer 的字节。外部 .bin 取不到 —— 导入时只收了一个文件,旁边那份不在。"""
    out: list[bytes] = []
    for buffer in document.get("buffers") or []:
        uri = buffer.get("uri")
        if uri is None:
            if blob is None:
                raise UnsupportedModel("modelMeshErr_missingBinChunk")
            out.append(blob)
        elif uri.startswith("data:"):
            out.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            raise UnsupportedModel("modelMeshErr_externalBuffer", uri=uri)
    return out


def _accessor(document: dict, buffers: list[bytes], index: int) -> np.ndarray:
    """一个访问器读成 (count, components) 的数组。"""
    accessor = (document.get("accessors") or [])[index]
    if "sparse" in accessor:
        raise UnsupportedModel("modelMeshErr_sparseAccessor")
    components = _COUNTS[accessor["type"]]
    dtype = np.dtype(_COMPONENTS[accessor["componentType"]])
    count = int(accessor["count"])
    if accessor.get("bufferView") is None:
        return np.zeros((count, components), dtype=np.float64)
    view = (document.get("bufferViews") or [])[accessor["bufferView"]]
    data = buffers[view.get("buffer", 0)]
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or components * dtype.itemsize
    if stride == components * dtype.itemsize:
        values = np.frombuffer(data, dtype=dtype, count=count * components, offset=start)
        return values.reshape(count, components).astype(np.float64)
    # 交错缓冲:一行里还夹着别的属性,按步长一行行取出这一段。
    rows = np.frombuffer(data, dtype=np.uint8, count=count * stride, offset=start).reshape(count, stride)
    wanted = rows[:, : components * dtype.itemsize].copy()
    return wanted.view(dtype).reshape(count, components).astype(np.float64)


def _matrix(node: dict) -> np.ndarray:
    """节点的局部矩阵。glTF 的 `matrix` 是**按列**排的,所以读进来要转置。"""
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
    matrix = np.eye(4)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    matrix[:3, :3] = rotation * np.asarray(node.get("scale", [1, 1, 1]))[None, :]
    matrix[:3, 3] = node.get("translation", [0, 0, 0])
    return matrix


def _nodes(document: dict) -> list[tuple[np.ndarray, int]]:
    """场景树上每个带网格的节点,以及它的世界矩阵(在模型自己的坐标系里)。

    按 `scenes[scene]` 的根往下走,而不是遍历 `nodes` —— 不在场景里的节点是没被用上的备件,
    照单全收会把它们画到原点上。
    """
    nodes = document.get("nodes") or []
    scenes = document.get("scenes") or []
    scene = scenes[document.get("scene", 0)] if scenes else {"nodes": list(range(len(nodes)))}
    found: list[tuple[np.ndarray, int]] = []
    seen: set[int] = set()

    def walk(index: int, parent: np.ndarray) -> None:
        if index in seen or index >= len(nodes):  # 环形引用是坏文件,不是死循环的理由
            return
        seen.add(index)
        node = nodes[index]
        matrix = parent @ _matrix(node)
        if node.get("mesh") is not None:
            found.append((matrix, int(node["mesh"])))
        for child in node.get("children") or []:
            walk(int(child), matrix)

    for root in scene.get("nodes") or []:
        walk(int(root), np.eye(4))
    return found


def _face_count(document: dict, primitive: dict) -> int:
    """这个图元有几个三角形 —— **只看访问器上声明的数量,不碰字节**。"""
    accessors = document.get("accessors") or []
    source = primitive.get("indices")
    if source is None:
        source = (primitive.get("attributes") or {}).get("POSITION")
    if source is None:
        return 0
    return int(accessors[int(source)].get("count", 0)) // 3


def _primitive(document: dict, buffers: list[bytes], primitive: dict, matrix: np.ndarray) -> Mesh | None:
    position = (primitive.get("attributes") or {}).get("POSITION")
    if position is None:
        return None
    vertices = _accessor(document, buffers, int(position))[:, :3]
    if primitive.get("indices") is None:
        faces = np.arange(len(vertices) - len(vertices) % 3, dtype=np.int64).reshape(-1, 3)
    else:
        faces = _accessor(document, buffers, int(primitive["indices"]))[:, 0].astype(np.int64)
        faces = faces[: len(faces) - len(faces) % 3].reshape(-1, 3)
    if not len(faces):
        return None
    points = np.concatenate([vertices, np.ones((len(vertices), 1))], axis=1) @ matrix.T
    return Mesh(points[:, :3], faces, color=_base_color(document, primitive),
                metalness=_metalness(document, primitive))


def _material(document: dict, primitive: dict) -> dict:
    index = primitive.get("material")
    if index is None:
        return {}
    return (document.get("materials") or [])[int(index)] or {}


def _base_color(document: dict, primitive: dict) -> np.ndarray | None:
    """基色。glTF 的 baseColorFactor **已经是线性的**,和 raster 里的约定一致,直接用。"""
    factor = (_material(document, primitive).get("pbrMetallicRoughness") or {}).get("baseColorFactor")
    if not factor:
        return None
    return np.clip(np.asarray(factor[:3], dtype=np.float64), 0, 1)


def _metalness(document: dict, primitive: dict) -> float | None:
    pbr = _material(document, primitive).get("pbrMetallicRoughness")
    if pbr is None or "metallicFactor" not in pbr:
        return None
    return float(np.clip(pbr["metallicFactor"], 0, 1))
