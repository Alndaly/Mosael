"""3D 场景 → 白模参考图 / 运镜参考视频。**在后端渲**。

为什么要有这一份:工作台的渲染器是浏览器里的 three.js,而工作流跑在后端 —— 此前"用 3D
白模给生成做参考"只能手动在工作台里点「生成素材」,整片自动生成的流程够不着它。于是自动
流程的每一镜只有一段文字提示词,构图、机位、人物站位全靠模型猜,六镜之间谁也对不上谁。

这里渲的是**白模**:几何、机位、光的方向与影子和工作台一致(见 sampling / meshes / raster
三个文件开头的对照说明),材质只取每个物体的颜色做漫反射。它是给图像/视频模型看"构图和
光从哪来"的,不是成片。

导入的 GLB 模型渲不出来(可能带 Draco/KTX2 压缩),`skipped_models` 如实报出来。
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.domain.scene_render.meshes import UNSUPPORTED, meshes_for
from app.domain.scene_render.raster import (
    Lighting,
    PointLight,
    Triangles,
    hex_to_linear,
    kelvin_rgb,
    render,
    sun_direction,
)
from app.domain.scene_render.sampling import CameraPose, sample_camera, sample_object
from app.domain.scene_types import SceneContent, SceneObject, SceneShot

#: 镜头比例 → 参考帧尺寸。短边 540:图像模型的参考图、视频模型的参考视频都收得下,
#: 又不至于让后端一帧渲上好几秒。
FRAME_SIZES = {"16:9": (960, 540), "9:16": (540, 960), "1:1": (720, 720)}
#: 静帧超采样倍数(渲大再缩小 = 抗锯齿)。视频帧不超采样:它传的是运动,不是边缘。
STILL_SUPERSAMPLE = 2
#: 运镜参考视频:渲 12 帧/秒,编码成 24 帧/秒(重复帧)。参考视频传的是镜头怎么走,
#: 12 帧足够看清,而渲染时间减半。
VIDEO_RENDER_FPS = 12
VIDEO_OUTPUT_FPS = 24


class SceneRenderError(ValueError):
    """这个场景/镜头渲不了(镜头不存在、没有机位)。"""


@dataclass(frozen=True)
class RenderedFrame:
    image: Image.Image
    camera: CameraPose
    skipped_models: int


def _rotation(degrees: tuple[float, float, float]) -> np.ndarray:
    """three.js 欧拉角 'XYZ' 顺序的旋转矩阵:R = Rx · Ry · Rz。"""
    x, y, z = (math.radians(v) for v in degrees)
    rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
    return rx @ ry @ rz


def _local_matrix(position, rotation, scale) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, :3] = _rotation(rotation) * np.asarray(scale)[None, :]
    matrix[:3, 3] = position
    return matrix


def _world_matrices(content: SceneContent, shot: SceneShot, time: float) -> dict[str, np.ndarray]:
    """每个物体此刻的世界矩阵。分组的变换一层层乘下去(和 three.js 的场景树一样)。"""
    objects = {obj.id: obj for obj in content.objects}
    local: dict[str, np.ndarray] = {}
    for obj in content.objects:
        if obj.kind == "camera":
            local[obj.id] = np.eye(4)  # 相机的姿态另算(见 _camera),它不带着别的物体走
            continue
        pose = sample_object(obj, shot, time)
        local[obj.id] = _local_matrix(pose.position, pose.rotation, pose.scale)
    world: dict[str, np.ndarray] = {}

    def resolve(object_id: str) -> np.ndarray:
        if object_id not in world:
            parent = objects[object_id].parent_id
            world[object_id] = (resolve(parent) @ local[object_id]) if parent else local[object_id]
        return world[object_id]

    for obj in content.objects:
        resolve(obj.id)
    return world


def _visible(obj: SceneObject, objects: dict[str, SceneObject]) -> bool:
    """自己和所有上级都没被隐藏。"""
    current: SceneObject | None = obj
    while current is not None:
        if current.hidden:
            return False
        current = objects.get(current.parent_id) if current.parent_id else None
    return True


def _camera(content: SceneContent, shot: SceneShot, time: float, world: dict[str, np.ndarray]) -> CameraPose:
    camera = next((obj for obj in content.objects if obj.id == shot.camera_id), None)
    if camera is None or camera.kind != "camera":
        raise SceneRenderError(f"镜头「{shot.name}」没有可用的机位")
    pose = sample_camera(camera, shot, time)
    if camera.parent_id:
        # 在分组里的相机:位置跟着分组走;看向的点是世界坐标(three.js 的 lookAt 就是这么定义的)。
        parent = world[camera.parent_id]
        position = tuple((parent @ np.array([*pose.position, 1.0]))[:3])
        return CameraPose(position, pose.target, pose.fov)
    return pose


def _triangles(content: SceneContent, world: dict[str, np.ndarray]) -> tuple[Triangles, int]:
    objects = {obj.id: obj for obj in content.objects}
    corners, albedo, metal = [], [], []
    skipped = 0
    for obj in content.objects:
        if not _visible(obj, objects):
            continue
        if obj.kind in UNSUPPORTED:
            skipped += 1
            continue
        matrix = world[obj.id]
        color = hex_to_linear(obj.color)
        for mesh in meshes_for(obj):
            points = np.concatenate([mesh.vertices, np.ones((len(mesh.vertices), 1))], axis=1) @ matrix.T
            corners.append(points[:, :3][mesh.faces])
            albedo.append(np.repeat(color[None, :], len(mesh.faces), axis=0))
            metal.append(np.full(len(mesh.faces), obj.metalness))
    if not corners:
        return Triangles(np.zeros((0, 3, 3)), np.zeros((0, 3)), np.zeros(0)), skipped
    return Triangles(np.concatenate(corners), np.concatenate(albedo), np.concatenate(metal)), skipped


def _lighting(content: SceneContent, world: dict[str, np.ndarray]) -> Lighting:
    objects = {obj.id: obj for obj in content.objects}
    light = content.lighting
    lamps = [
        PointLight(position=world[obj.id][:3, 3], color=hex_to_linear(obj.color), intensity=obj.intensity)
        for obj in content.objects
        if obj.kind == "light" and _visible(obj, objects)
    ]
    return Lighting(
        ambient=content.ambient,
        sun_direction=sun_direction(light.azimuth, light.elevation),
        sun_color=kelvin_rgb(light.temperature),
        sun_intensity=light.intensity,
        softness=light.softness,
        points=lamps,
    )


def find_shot(content: SceneContent, shot_id: str) -> SceneShot:
    shot = next((one for one in content.shots if one.id == shot_id), None)
    if shot is None:
        raise SceneRenderError(f"场景里没有镜头 {shot_id}")
    return shot


def render_frame(content: SceneContent, shot_id: str, time: float, *, supersample: int = STILL_SUPERSAMPLE) -> RenderedFrame:
    """这个镜头在第 `time` 秒的白模画面。"""
    shot = find_shot(content, shot_id)
    world = _world_matrices(content, shot, time)
    camera = _camera(content, shot, time, world)
    tris, skipped = _triangles(content, world)
    width, height = FRAME_SIZES[shot.aspect]
    background = np.array([int(content.background[i:i + 2], 16) / 255 for i in (1, 3, 5)])
    pixels = render(
        tris, _lighting(content, world),
        camera_position=np.asarray(camera.position, dtype=np.float64),
        camera_target=np.asarray(camera.target, dtype=np.float64),
        fov=camera.fov, width=width * supersample, height=height * supersample, background=background,
    )
    image = Image.fromarray(pixels, "RGB")
    if supersample > 1:
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    return RenderedFrame(image=image, camera=camera, skipped_models=skipped)


def render_shot_video(content: SceneContent, shot_id: str, target: Path) -> Path:
    """整个镜头的运镜参考视频(H.264 MP4)。物体有动画的也一起动。"""
    from app.core.child_process import run_logged
    from app.core.config import settings

    shot = find_shot(content, shot_id)
    count = max(2, int(math.ceil(shot.duration * VIDEO_RENDER_FPS)) + 1)
    with tempfile.TemporaryDirectory(prefix="mosael-graybox-") as folder:
        for index in range(count):
            time = min(shot.duration, index / VIDEO_RENDER_FPS)
            render_frame(content, shot_id, time, supersample=1).image.save(Path(folder) / f"{index:05d}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        completed = run_logged(
            [
                settings.ffmpeg, "-y", "-v", "error",
                "-framerate", str(VIDEO_RENDER_FPS), "-i", str(Path(folder) / "%05d.png"),
                "-vf", f"fps={VIDEO_OUTPUT_FPS}", "-t", f"{shot.duration:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
            ],
            what="编码白模运镜视频",
            capture_output=True,
            text=True,
            timeout=600,
        )
    if completed.returncode != 0 or not target.is_file():
        raise SceneRenderError(f"白模运镜视频编码失败:{(completed.stderr or '').strip()[-300:]}")
    return target


__all__ = [
    "FRAME_SIZES",
    "RenderedFrame",
    "SceneRenderError",
    "find_shot",
    "render_frame",
    "render_shot_video",
]
