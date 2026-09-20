"""把一组世界坐标下的三角形,从一台机位渲成一张图。z-buffer + 主光阴影图。

光照对照工作台(`SceneViewport.tsx` / `lighting.ts`,由 `contracts/scene-3d-cases.json` 钉住):半球环境光(天空白、地面 #666879,强度 = 场景的
ambient)+ 一盏平行主光(方向由方位角/高度角定,颜色按色温,带阴影)+ 场景里的点光源;
ACES Filmic 色调映射、sRGB 输出。材质只取漫反射 —— 白模要传的是**光的结构和构图**,
不是高光(见前端 clayReference.ts 那段"为什么送灰模")。

**这里不是工作台那个 three.js 渲染器**,两者的软阴影、抗锯齿细节会有差别。一致的是必须
一致的那些:几何(meshes.py)、机位与时间采样(sampling.py)、投影(竖直 fov、Y 朝上、
看向 target)、光的方向与颜色。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

NEAR = 0.05
#: 工作台地面那种偏蓝的灰(HemisphereLight 的 groundColor 0x666879)。
_GROUND = (0x66 / 255, 0x68 / 255, 0x79 / 255)


@dataclass
class Triangles:
    """世界坐标下的一批三角形,以及每个三角形的材质。"""

    corners: np.ndarray  # (t, 3, 3)
    albedo: np.ndarray  # (t, 3) 线性空间
    metalness: np.ndarray  # (t,)


@dataclass
class PointLight:
    position: np.ndarray
    color: np.ndarray  # 线性
    intensity: float


@dataclass
class Lighting:
    ambient: float
    sun_direction: np.ndarray  # 指向光源的单位向量
    sun_color: np.ndarray  # 线性
    sun_intensity: float
    softness: float
    points: list[PointLight]


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def hex_to_linear(value: str) -> np.ndarray:
    value = value.lstrip("#")
    return srgb_to_linear(np.array([int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]))


def kelvin_rgb(kelvin: float) -> np.ndarray:
    """对照前端 lighting.kelvinRgb(Tanner Helland 的近似);两侧的值由 `contracts/scene-3d-cases.json` 钉住。

    前端把结果当线性色用,这里也一样。"""
    t = min(40000, max(1000, kelvin)) / 100
    red = 255 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    green = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    blue = 255 if t >= 66 else 0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    return np.clip(np.array([red, green, blue]) / 255, 0, 1)


def sun_direction(azimuth: float, elevation: float) -> np.ndarray:
    """方位角 0 是 +Z(相机默认所在的一侧),顺时针转向 +X。对照 SceneViewport.sunDirection。"""
    a, e = math.radians(azimuth), math.radians(elevation)
    return np.array([math.sin(a) * math.cos(e), math.sin(e), math.cos(a) * math.cos(e)])


def look_at(position: np.ndarray, target: np.ndarray) -> np.ndarray:
    """世界 → 相机的 4x4 矩阵。相机看向 -Z、Y 朝上(three.js 的约定)。"""
    forward = target - position
    forward = forward / np.linalg.norm(forward)
    up = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(forward, up))) > 0.999:  # 正上/正下看时换一个参考轴,否则叉乘为零
        up = np.array([0.0, 0.0, -1.0])
    right = np.cross(forward, up)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    view = np.eye(4)
    view[0, :3], view[1, :3], view[2, :3] = right, true_up, -forward
    view[:3, 3] = -view[:3, :3] @ position
    return view


def _face_normals(corners: np.ndarray) -> np.ndarray:
    n = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.where(length == 0, 1, length)


def _clip_near(cam: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """相机空间下,把三角形裁到近平面前面。返回 (新三角形, 它们来自原来的哪一个)。

    室内机位时,地板和墙的大三角形有一半在相机背后 —— 直接丢掉,画面就少了一块地;直接投影,
    背后的顶点会翻到画面另一侧。只有跨过近平面的那几个需要逐个处理,其余原样保留。
    """
    z = cam[:, :, 2]
    front = z < -NEAR
    whole = front.all(axis=1)
    partial = np.where(front.any(axis=1) & ~whole)[0]
    tris = [cam[whole]]
    origin = [np.where(whole)[0]]
    extra, extra_origin = [], []
    for index in partial:
        polygon = []
        points = cam[index]
        for k in range(3):
            a, b = points[k], points[(k + 1) % 3]
            a_in, b_in = a[2] < -NEAR, b[2] < -NEAR
            if a_in:
                polygon.append(a)
            if a_in != b_in:
                u = (-NEAR - a[2]) / (b[2] - a[2])
                polygon.append(a + (b - a) * u)
        for k in range(1, len(polygon) - 1):
            extra.append([polygon[0], polygon[k], polygon[k + 1]])
            extra_origin.append(index)
    if extra:
        tris.append(np.asarray(extra))
        origin.append(np.asarray(extra_origin, dtype=np.int64))
    return np.concatenate(tris), np.concatenate(origin)


def _rasterize(screen: np.ndarray, depth_key: np.ndarray, width: int, height: int,
               keep_nearest_larger: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """逐三角形填 z-buffer。

    `screen`:(t, 3, 2) 像素坐标;`depth_key`:(t, 3) 每个顶点的深度键 —— 透视时是 1/z
    (在屏幕空间里线性,越大越近),正交时是沿光线的距离(越小越近)。
    返回 (深度键缓冲, 三角形编号缓冲, 重心坐标缓冲 (h, w, 3))。
    """
    fill = -np.inf if keep_nearest_larger else np.inf
    zbuf = np.full((height, width), fill)
    ids = np.full((height, width), -1, dtype=np.int64)
    bary = np.zeros((height, width, 3))
    xs_all = np.arange(width) + 0.5
    ys_all = np.arange(height) + 0.5
    for i in range(len(screen)):
        (x0, y0), (x1, y1), (x2, y2) = screen[i]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        left = max(int(math.floor(min(x0, x1, x2))), 0)
        right = min(int(math.ceil(max(x0, x1, x2))), width)
        top = max(int(math.floor(min(y0, y1, y2))), 0)
        bottom = min(int(math.ceil(max(y0, y1, y2))), height)
        if left >= right or top >= bottom:
            continue
        px = xs_all[left:right][None, :]
        py = ys_all[top:bottom][:, None]
        w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
        w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        d = w0 * depth_key[i, 0] + w1 * depth_key[i, 1] + w2 * depth_key[i, 2]
        patch = zbuf[top:bottom, left:right]
        better = inside & ((d > patch) if keep_nearest_larger else (d < patch))
        if not better.any():
            continue
        patch[better] = d[better]
        ids[top:bottom, left:right][better] = i
        bary[top:bottom, left:right][better] = np.stack([w0, w1, w2], axis=-1)[better]
    return zbuf, ids, bary


def _shadow_factor(world: np.ndarray, normals: np.ndarray, tris: Triangles, lighting: Lighting,
                   resolution: int = 1024) -> np.ndarray:
    """每个可见像素被主光照到多少(0 全在影子里,1 全亮)。正交阴影图,和工作台的 fitShadow 同一个框法。"""
    corners = tris.corners.reshape(-1, 3)
    center = (corners.min(axis=0) + corners.max(axis=0)) / 2
    radius = max(float(np.linalg.norm(corners - center, axis=1).max()), 1.0)
    direction = lighting.sun_direction
    light_view = look_at(center + direction * radius * 3, center)
    extent = radius * 1.25

    def to_light(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        homogeneous = np.concatenate([points, np.ones((*points.shape[:-1], 1))], axis=-1)
        local = homogeneous @ light_view.T
        pixel = (local[..., :2] / extent * 0.5 + 0.5) * resolution
        pixel[..., 1] = resolution - pixel[..., 1]
        return pixel, -local[..., 2]  # 沿光线的距离,越小越近

    screen, distance = to_light(tris.corners)
    depth_map, _, _ = _rasterize(screen, distance, resolution, resolution, keep_nearest_larger=False)
    # **法线偏移**:取样点先沿法线推出去两个阴影图像素,再去查。不推的话,斜照的大平面(墙、地)
    # 会在自己身上投出一道道细纹(shadow acne)—— 前端用 shadow.normalBias 治同一个病。
    texel = 2 * extent / resolution
    pixel, dist = to_light(world + normals * texel * 2)
    bias = texel
    lit = np.zeros(pixel.shape[:-1])
    #: 软硬:越软,取样的邻域越大(工作台用 PCFSoft 的模糊半径表达同一件事)。
    reach = 1 + int(round(lighting.softness * 3))
    samples = 0
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            ix = np.clip(pixel[..., 0].astype(np.int64) + dx, 0, resolution - 1)
            iy = np.clip(pixel[..., 1].astype(np.int64) + dy, 0, resolution - 1)
            occluder = depth_map[iy, ix]
            lit += (dist - bias <= occluder) | ~np.isfinite(occluder)
            samples += 1
    return lit / samples


def _aces(color: np.ndarray) -> np.ndarray:
    """three.js 的 ACESFilmicToneMapping(曝光 1)。"""
    color = color / 0.6
    m1 = np.array([[0.59719, 0.07600, 0.02840], [0.35458, 0.90834, 0.13383], [0.04823, 0.01566, 0.83777]])
    m2 = np.array([[1.60475, -0.10208, -0.00327], [-0.53108, 1.10813, -0.07276], [-0.07367, -0.00605, 1.07602]])
    v = color @ m1
    a = v * (v + 0.0245786) - 0.000090537
    b = v * (0.983729 * v + 0.4329510) + 0.238081
    return np.clip((a / b) @ m2, 0, 1)


def _linear_to_srgb(color: np.ndarray) -> np.ndarray:
    return np.where(color <= 0.0031308, color * 12.92, 1.055 * np.power(np.maximum(color, 0), 1 / 2.4) - 0.055)


def render(tris: Triangles, lighting: Lighting, *, camera_position: np.ndarray, camera_target: np.ndarray,
           fov: float, width: int, height: int, background: np.ndarray) -> np.ndarray:
    """渲一帧,返回 (h, w, 3) 的 uint8 sRGB。`background` 是 0..1 的 sRGB。"""
    #: 背景是场景数据里的那个 sRGB 颜色,**不过色调映射**(three.js 的清屏色也不过)。
    out = np.broadcast_to(np.asarray(background, dtype=np.float64), (height, width, 3)).copy()
    empty = (out * 255).astype(np.uint8)
    if len(tris.corners) == 0:
        return empty
    normals = _face_normals(tris.corners)
    # 背面剔除:法线背对相机的面看不见(所有基本体都是封闭的凸体,见 meshes._outward)。
    facing = np.einsum("ij,ij->i", normals, camera_position - tris.corners.mean(axis=1)) > 0
    view = look_at(camera_position, camera_target)
    homogeneous = np.concatenate([tris.corners[facing], np.ones((int(facing.sum()), 3, 1))], axis=-1)
    cam = (homogeneous @ view.T)[..., :3]
    kept = np.where(facing)[0]
    clipped, origin = _clip_near(cam)
    origin = kept[origin]
    if len(clipped) == 0:
        return empty
    focal = (height / 2) / math.tan(math.radians(fov) / 2)
    depth = -clipped[..., 2]
    screen = np.empty((*clipped.shape[:2], 2))
    screen[..., 0] = width / 2 + clipped[..., 0] / depth * focal
    screen[..., 1] = height / 2 - clipped[..., 1] / depth * focal
    zbuf, ids, bary = _rasterize(screen, 1 / depth, width, height, keep_nearest_larger=True)
    hit = ids >= 0
    if not hit.any():
        return empty

    # 可见像素的世界坐标:透视校正地插值相机空间位置,再变回世界。
    tri = ids[hit]
    w = bary[hit]
    inv = 1 / depth[tri]  # (n, 3)
    weights = w * inv
    weights /= weights.sum(axis=1, keepdims=True)
    cam_points = np.einsum("ni,nij->nj", weights, clipped[tri])
    world = (np.concatenate([cam_points, np.ones((len(cam_points), 1))], axis=1) @ np.linalg.inv(view).T)[:, :3]
    source = origin[tri]
    n = normals[source]
    albedo = tris.albedo[source] * (1 - 0.7 * tris.metalness[source])[:, None]

    sky = np.ones(3)
    ground = srgb_to_linear(np.array(_GROUND))
    hemisphere = (ground + (sky - ground) * (0.5 * n[:, 1:2] + 0.5)) * lighting.ambient
    n_dot_l = np.clip(n @ lighting.sun_direction, 0, None)[:, None]
    shadow = _shadow_factor(world, n, tris, lighting)[:, None]
    irradiance = hemisphere + lighting.sun_color * lighting.sun_intensity * n_dot_l * shadow
    for lamp in lighting.points:
        to_lamp = lamp.position - world
        distance = np.linalg.norm(to_lamp, axis=1, keepdims=True)
        facing_lamp = np.clip(np.einsum("ij,ij->i", n, to_lamp / np.maximum(distance, 1e-6)), 0, None)[:, None]
        # three.js 点光源:distance=50、decay=2 的衰减。
        falloff = (1 / np.maximum(distance**2, 0.01)) * np.clip(1 - (distance / 50) ** 4, 0, 1) ** 2
        irradiance = irradiance + lamp.color * lamp.intensity * facing_lamp * falloff
    out[hit] = np.clip(_linear_to_srgb(_aces(albedo / math.pi * irradiance)), 0, 1)
    return (out * 255).astype(np.uint8)
