"""每种场景物体长什么样。**逐项对照前端 `sceneMeshes.geometryObject`**,由
`contracts/scene-3d-cases.json` 钉住(两侧各跑一遍,谁改了另一侧没跟上就一起红)。

尺寸、偏移、比例一个都不能自己发明:白模参考帧要和用户在工作台里看到的是同一个东西 ——
人物的身高、肩宽、头的位置决定了机位在不在视平线上,门洞的高度决定了人走不走得过去。
那边每一个数字的理由都写在注释里,这里只照搬。

几何在物体自己的坐标系里,Y 朝上,单位米。所有基本体都是凸的,所以面的朝向统一按
"法线背离这个基本体的中心"定(`_outward`)—— 不靠手写绕序,手写的绕序错一个面,那个面就
在背面剔除里消失了,而且只在某些角度看得出来。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.domain.scene_types import SceneObject

#: 这几种没有可见几何:相机不拍自己(前端标了 editorOnly),分组只是容器,灯另算光照。
NO_GEOMETRY = {"camera", "group", "light"}
#: 导入的模型不在这里:它的几何在**文件**里,而这一份是纯函数 —— 只看物体,不碰磁盘。
#: 由 `model_mesh.ModelLibrary` 读出来,渲染器在 `_triangles` 里按 model_id 取(见那边的说明)。
FROM_FILE = {"model"}


@dataclass
class Mesh:
    vertices: np.ndarray  # (n, 3)
    faces: np.ndarray  # (m, 3) int
    #: 线性空间的基色。**None = 跟随物体自己的 color** —— 基本体都是这样,一个物体一个颜色。
    #: 导入的模型不一样:一份 GLB 里有多种材质,颜色得跟着图元走,否则整件道具会被刷成一色。
    color: np.ndarray | None = None
    #: 同上。None = 跟随物体的 metalness。
    metalness: float | None = None


def _outward(vertices: np.ndarray, faces: np.ndarray, center: np.ndarray) -> np.ndarray:
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    normals = np.cross(b - a, c - a)
    outward = np.einsum("ij,ij->i", normals, (a + b + c) / 3 - center) >= 0
    fixed = faces.copy()
    fixed[~outward] = fixed[~outward][:, [0, 2, 1]]
    return fixed


def _mesh(vertices: list, faces: list, offset=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> Mesh:
    v = np.asarray(vertices, dtype=np.float64)
    f = _outward(v, np.asarray(faces, dtype=np.int64), np.zeros(3))
    v = v * np.asarray(scale) + np.asarray(offset)
    return Mesh(v, f)


def box(w: float, h: float, d: float, x: float = 0.0, y: float | None = None, z: float = 0.0) -> Mesh:
    """three.js 的 BoxGeometry(w, h, d),摆在 (x, y, z);y 缺省时底面贴地(y = h/2)。"""
    hx, hy, hz = w / 2, h / 2, d / 2
    vertices = [(sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return _mesh(vertices, faces, (x, h / 2 if y is None else y, z))


def sphere(radius: float, width_segments: int = 24, height_segments: int = 16, offset=(0.0, 0.0, 0.0)) -> Mesh:
    vertices = [(0.0, radius, 0.0)]
    for i in range(1, height_segments):
        phi = math.pi * i / height_segments
        for j in range(width_segments):
            theta = 2 * math.pi * j / width_segments
            vertices.append((radius * math.sin(phi) * math.cos(theta), radius * math.cos(phi),
                             radius * math.sin(phi) * math.sin(theta)))
    vertices.append((0.0, -radius, 0.0))
    faces = []
    ring = lambda i, j: 1 + (i - 1) * width_segments + (j % width_segments)  # noqa: E731
    for j in range(width_segments):
        faces.append((0, ring(1, j), ring(1, j + 1)))
        faces.append((len(vertices) - 1, ring(height_segments - 1, j + 1), ring(height_segments - 1, j)))
    for i in range(1, height_segments - 1):
        for j in range(width_segments):
            faces.append((ring(i, j), ring(i + 1, j), ring(i + 1, j + 1)))
            faces.append((ring(i, j), ring(i + 1, j + 1), ring(i, j + 1)))
    return _mesh(vertices, faces, offset)


def cylinder(radius: float, height: float, segments: int = 24, offset=(0.0, 0.0, 0.0)) -> Mesh:
    vertices = []
    for y in (-height / 2, height / 2):
        for j in range(segments):
            theta = 2 * math.pi * j / segments
            vertices.append((radius * math.cos(theta), y, radius * math.sin(theta)))
    bottom_center, top_center = len(vertices), len(vertices) + 1
    vertices += [(0.0, -height / 2, 0.0), (0.0, height / 2, 0.0)]
    faces = []
    for j in range(segments):
        a, b = j, (j + 1) % segments
        faces += [(a, b, segments + b), (a, segments + b, segments + a)]
        faces += [(bottom_center, a, b), (top_center, segments + b, segments + a)]
    return _mesh(vertices, faces, offset)


def capsule(radius: float, length: float, radial: int = 12, cap: int = 4,
            offset=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> Mesh:
    """three.js 的 CapsuleGeometry(radius, length):两头半球、中间圆柱,总高 length + 2r。"""
    length = max(length, 0.0)
    rows: list[tuple[float, float]] = []  # (y, ring radius)
    for i in range(cap + 1):  # 上半球,从顶往赤道
        phi = (math.pi / 2) * i / cap
        rows.append((length / 2 + radius * math.cos(phi), radius * math.sin(phi)))
    for i in range(cap + 1):  # 下半球,从赤道往底
        phi = (math.pi / 2) * i / cap
        rows.append((-length / 2 - radius * math.sin(phi), radius * math.cos(phi)))
    vertices, faces = [], []
    for y, r in rows:
        for j in range(radial):
            theta = 2 * math.pi * j / radial
            vertices.append((r * math.cos(theta), y, r * math.sin(theta)))
    for i in range(len(rows) - 1):
        for j in range(radial):
            a, b = i * radial + j, i * radial + (j + 1) % radial
            c, d = a + radial, b + radial
            faces += [(a, c, d), (a, d, b)]
    # 顶点和底点各一圈半径为 0 的环,会产生退化三角形 —— 面积为零,光栅化时自然被丢掉。
    return _mesh(vertices, faces, offset, scale)


def meshes_for(obj: SceneObject) -> list[Mesh]:
    """这个物体在它自己的坐标系里的全部几何。"""
    p = obj.parameters
    kind = obj.kind
    if kind in NO_GEOMETRY or kind in FROM_FILE:
        return []
    if kind == "box":
        return [box(p.width, p.height, p.depth)]
    if kind == "plane":
        return [box(p.width, 0.04, p.depth, 0, -0.02, 0)]
    if kind == "sphere":
        return [sphere(p.radius, offset=(0, p.radius, 0))]
    if kind == "cylinder":
        return [cylinder(p.radius, p.height, offset=(0, p.height / 2, 0))]
    if kind == "room":
        w, h, d = p.width, p.height, p.depth
        door, dh = min(p.door_width, w * 0.85), min(p.door_height, h * 0.9)
        side = (w - door) / 2
        parts = [box(w, 0.08, d, 0, -0.04, 0), box(0.15, h, d, -w / 2), box(0.15, h, d, w / 2)]
        for z in (-d / 2, d / 2):
            parts += [
                box(side, h, 0.15, -(w + door) / 4, h / 2, z),
                box(side, h, 0.15, (w + door) / 4, h / 2, z),
                box(door, h - dh, 0.15, 0, dh + (h - dh) / 2, z),
            ]
        return parts
    if kind == "stairs":
        return [
            box(p.width, p.height * (i + 1) / p.steps, p.depth / p.steps, 0,
                p.height * (i + 1) / p.steps / 2, -p.depth / 2 + p.depth * (i + 0.5) / p.steps)
            for i in range(p.steps)
        ]
    if kind == "figure":
        return _figure(p.height, max(p.width, 0.2), max(p.depth, 0.12))
    if kind == "table":
        top = min(0.06, p.height * 0.1)
        leg = min(0.08, min(p.width, p.depth) * 0.09)
        parts = [box(p.width, top, p.depth, 0, p.height - top / 2)]
        for sx in (-1, 1):
            for sz in (-1, 1):
                parts.append(box(leg, p.height - top, leg, sx * (p.width - leg) / 2 * 0.92,
                                 (p.height - top) / 2, sz * (p.depth - leg) / 2 * 0.92))
        return parts
    return []


def _figure(h: float, shoulders: float, thickness: float) -> list[Mesh]:
    """人物:给构图当尺子的概括人形。比例和前端一模一样(1.7 米人体的常见分法)。"""
    head_r, leg_h, torso_h, arm_h = h * 0.066, h * 0.47, h * 0.33, h * 0.36
    return [
        capsule(thickness * 0.42, leg_h - thickness * 0.84, offset=(-shoulders * 0.22, leg_h / 2, 0)),
        capsule(thickness * 0.42, leg_h - thickness * 0.84, offset=(shoulders * 0.22, leg_h / 2, 0)),
        capsule(thickness * 0.62, torso_h - thickness * 1.24, radial=14,
                offset=(0, leg_h + torso_h / 2, 0), scale=(shoulders / (thickness * 1.24), 1, 1)),
        capsule(thickness * 0.3, arm_h - thickness * 0.6, offset=(-shoulders * 0.62, leg_h + torso_h - arm_h / 2, 0)),
        capsule(thickness * 0.3, arm_h - thickness * 0.6, offset=(shoulders * 0.62, leg_h + torso_h - arm_h / 2, 0)),
        capsule(head_r * 0.4, head_r * 0.6, offset=(0, leg_h + torso_h + head_r * 0.3, 0)),
        sphere(head_r, offset=(0, h - head_r, 0)),
    ]
