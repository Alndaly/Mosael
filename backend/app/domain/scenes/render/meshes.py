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

from app.domain.scenes.types import FigurePose, SceneObject

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


def _rotation(degrees: tuple[float, float, float]) -> np.ndarray:
    """three.js 欧拉角 'XYZ' 顺序:R = Rx · Ry · Rz(和 render.__init__ 的 _rotation 同一份约定)。"""
    x, y, z = (math.radians(v) for v in degrees)
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return rx @ ry @ rz


def _local_matrix(position, rotation_deg, scale=(1.0, 1.0, 1.0)) -> np.ndarray:
    """three.js Object3D 的局部变换:T(position) · R(rotation) · S(scale)。"""
    matrix = np.eye(4)
    matrix[:3, :3] = _rotation(rotation_deg) * np.asarray(scale, dtype=np.float64)[None, :]
    matrix[:3, 3] = np.asarray(position, dtype=np.float64)
    return matrix


#: 关节层级(名字 → 父关节),和前端 mannequinRig.createMannequin 的 pivot 层级一致。
_JOINT_PARENTS = {
    "hips": None, "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
    "shoulderL": "chest", "upperArmL": "shoulderL", "forearmL": "upperArmL", "handL": "forearmL",
    "shoulderR": "chest", "upperArmR": "shoulderR", "forearmR": "upperArmR", "handR": "forearmR",
    "thighL": "hips", "shinL": "thighL", "footL": "shinL",
    "thighR": "hips", "shinR": "thighR", "footR": "shinR",
}

#: 关节在父级局部坐标里的位置(未缩放,s=1)。左(L)在 +X 侧、面朝 +Z,和前端 pivot() 一致。
_JOINT_OFFSETS = {
    "hips": (0.0, 0.95, 0.0), "spine": (0.0, 0.15, 0.0), "chest": (0.0, 0.2, 0.0),
    "neck": (0.0, 0.18, 0.0), "head": (0.0, 0.06, 0.0),
    "shoulderL": (0.08, 0.11, 0.0), "upperArmL": (0.1, 0.0, 0.0),
    "forearmL": (0.0, -0.23, 0.0), "handL": (0.0, -0.21, 0.0),
    "shoulderR": (-0.08, 0.11, 0.0), "upperArmR": (-0.1, 0.0, 0.0),
    "forearmR": (0.0, -0.23, 0.0), "handR": (0.0, -0.21, 0.0),
    "thighL": (0.105, -0.03, 0.0), "shinL": (0.0, -0.4, 0.0), "footL": (0.0, -0.38, 0.0),
    "thighR": (-0.105, -0.03, 0.0), "shinR": (0.0, -0.4, 0.0), "footR": (0.0, -0.38, 0.0),
}

#: 关节的建造顺序(父在子前)。
_JOINT_ORDER = [
    "hips", "spine", "chest", "neck", "head",
    "shoulderL", "upperArmL", "forearmL", "handL",
    "shoulderR", "upperArmR", "forearmR", "handR",
    "thighL", "shinL", "footL", "thighR", "shinR", "footR",
]


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
        return _figure(p.height, pose=obj.pose)
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


def _figure(h: float, pose: FigurePose | None) -> list[Mesh]:
    """可摆姿态的人形:**19 关节 FK 层级**,和前端 `mannequinRig.createMannequin` 逐项一致。

    默认(`pose` 为 None)= 直立站姿;给了 pose 就按它的角度表转每个关节(子随父动 = FK),
    再把髋部往下沉 `hips_drop`。比例全部从 `height` 推(s = height / 1.7),肩宽/厚度不再单独
    参数化 —— 原来那个「固定站姿 + width/depth」的 figure 换成关节版,默认看着仍是同一个站立人形。

    旋转约定:四肢段沿 -Y 下垂、面朝 +Z,欧拉角按 XYZ 序(和 three.js `Object3D.rotation` 一样)。
    """

    s = h / 1.7
    angles = pose.angles if pose else {}
    hips_drop = pose.hips_drop if pose else 0.0

    worlds: dict[str, np.ndarray] = {}
    for name in _JOINT_ORDER:
        ox, oy, oz = _JOINT_OFFSETS[name]
        if name == "hips":
            oy -= hips_drop
        local = _local_matrix((ox * s, oy * s, oz * s), angles.get(name, (0.0, 0.0, 0.0)))
        parent = _JOINT_PARENTS[name]
        worlds[name] = worlds[parent] @ local if parent else local

    def placed(joint: str, base: Mesh, position, rotation=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0)) -> Mesh:
        matrix = worlds[joint] @ _local_matrix(position, rotation, scale)
        vertices = np.concatenate([base.vertices, np.ones((len(base.vertices), 1))], axis=1) @ matrix.T
        return Mesh(vertices[:, :3], base.faces, base.color, base.metalness)

    def seg(joint: str, radius: float, length: float, y: float, sx: float = 1.0, sz: float = 1.0) -> Mesh:
        return placed(joint, capsule(radius * s, length * s, radial=14), (0.0, y * s, 0.0), scale=(sx, 1.0, sz))

    parts: list[Mesh] = [
        seg("hips", 0.135, 0.1, 0.03, 1.2, 0.85),  # 骨盆
        seg("spine", 0.125, 0.16, 0.09, 1.1, 0.8),  # 腰段
        # 胸廓:[0.15, 0.02] @ 段心 0 → 1.30 ± (0.02/2 + 0.15) = [1.14, 1.46]。**顶 1.46 到颈根
        # 1.516 那一段只能有脖子**,所以胸顶收在 1.46;原来的 1.63 会把脖子包住(那才是「没脖子」的原因)。
        seg("chest", 0.15, 0.02, 0.0, 1.3, 0.78),  # 胸廓
        seg("neck", 0.052, 0.06, 0.02),  # 脖子 [1.42, 1.58]:下段埋在胸里,上段露出、冠顶顶进头根
    ]
    # 头:一个球,略拉长。
    parts.append(placed("head", sphere(0.115 * s), (0.0, 0.1 * s, 0.0), scale=(0.92, 1.08, 0.98)))
    for side, sign in (("L", 1.0), ("R", -1.0)):
        # 锁骨:横躺的小胶囊(绕 Z 转 90°)。**肩这一组整块跟着胸廓往下收**:肩 pivot 此前钉在
        # 胸顶 1.46 上,锁骨横到 ±0.24、上臂根到 ±0.21,而胸半宽只有 0.195 —— 既在胸宽之外、
        # 顶又高过胸顶(锁骨顶 1.505 / 上臂顶 1.485),读起来是「一副衣架架在圆胸上」。现在
        # 肩 pivot 沉到 1.41(胸的上段),锁骨 length 0.04 @ x 偏移 0.05 → 跨 [0.065, 0.195]
        # (最外缘正好等于胸半宽,顶 1.455 压在胸顶 1.46 之下),上臂根收到 0.18 叠进胸廓侧面。
        # 脖子照旧露出 1.46–1.516:这一段里没有几何。
        parts.append(placed(f"shoulder{side}", capsule(0.045 * s, 0.04 * s, radial=10),
                            (sign * 0.05 * s, 0.0, 0.0), rotation=(0.0, 0.0, 90.0)))
        parts.append(seg(f"upperArm{side}", 0.055, 0.17, -0.115))
        parts.append(seg(f"forearm{side}", 0.047, 0.15, -0.1))
        parts.append(seg(f"hand{side}", 0.05, 0.09, -0.065))
    for side in ("L", "R"):
        parts.append(seg(f"thigh{side}", 0.085, 0.27, -0.19))
        parts.append(seg(f"shin{side}", 0.063, 0.27, -0.18))
        # 脚:box() 的 y 是**盒心**(给了 y 它自己加 h/2,和前端 BoxGeometry.position 对齐),
        # 盒心 -0.07、高 0.14、脚踝 0.14 → 世界 [0.0, 0.14]:脚底落在 y=0,小腿底 0.142 坐在脚里。
        parts.append(placed(f"foot{side}", box(0.09 * s, 0.14 * s, 0.25 * s, 0, -0.07 * s, 0.045 * s),
                            (0.0, 0.0, 0.0)))
    return parts
