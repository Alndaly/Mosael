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
    from app.core.text import blame_line

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
        # 挑**说明原因的那一行**,不按位置裁(见 core/text.blame_line)。
        raise SceneRenderError(f"白模运镜视频编码失败:{blame_line(completed.stderr or '', fallback='ffmpeg 没有说原因')}")
    return target


__all__ = [
    "FRAME_SIZES",
    "RenderedFrame",
    "SceneRenderError",
    "describe_camera_move",
    "find_shot",
    "render_frame",
    "render_shot_video",
]


def describe_camera_move(start: CameraPose, end: CameraPose) -> str:
    """把一个镜头的起止机位说成一句**镜头语言**(英文,直接进生成提示词)。

    模型读不懂坐标,但读得懂「35mm、机位 1.6 米、向主体推近 2 米、向左摇 10°」。这些数都是
    从机位轨迹里算出来的,不是再让 LLM 编一遍 —— 编的那一遍会和白模参考帧对不上。

    焦段按全画幅的竖直 24mm 画幅换算(和 Blender 那边的约定一致:lens = 12 / tan(fov/2))。
    """

    def lens(fov: float) -> int:
        return int(round(12 / math.tan(math.radians(fov) / 2)))

    p0, p1 = np.asarray(start.position), np.asarray(end.position)
    t0, t1 = np.asarray(start.target), np.asarray(end.target)
    parts = [f"{lens(start.fov)}mm lens, camera {p0[1]:.1f} m above the floor"]

    forward = (t0 - p0) / max(float(np.linalg.norm(t0 - p0)), 1e-6)
    right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
    right = right / max(float(np.linalg.norm(right)), 1e-6)
    moved = float(np.linalg.norm(p1 - p0))
    #: 三种移动分开认:**到主体的距离**变了是推拉,**绕着主体转**是环绕,**主体跟着一起走**是跟拍/横移。
    #: 只看"朝前走了多少"的话,环绕会被说成推近 —— 相机确实离主体的起点更近了,但那不是推。
    radial = float(np.linalg.norm(p0 - t0) - np.linalg.norm(p1 - t1))
    flat0, flat1 = (p0 - t0)[[0, 2]], (p1 - t1)[[0, 2]]
    orbit = math.degrees(math.atan2(flat0[0] * flat1[1] - flat0[1] * flat1[0], float(np.dot(flat0, flat1))))
    target_shift = float(np.linalg.norm(t1 - t0))
    sideways = "right" if float(np.dot(p1 - p0, right)) > 0 else "left"
    if moved > 0.15:
        if abs(orbit) > 12 and target_shift < moved * 0.5:
            parts.append(f"orbit {sideways} {abs(orbit):.0f}° around the subject")
        elif target_shift >= moved * 0.5 and abs(radial) < moved * 0.5:
            parts.append(f"tracking shot, camera travels {sideways if abs(float(np.dot(p1 - p0, right))) > moved * 0.5 else 'forward'} {moved:.1f} m with the subject")
        if abs(radial) > 0.3:
            parts.append(f"dolly {'in' if radial > 0 else 'out'} {abs(radial):.1f} m")
        vertical = float(p1[1] - p0[1])
        if abs(vertical) > 0.3:
            parts.append(f"crane {'up' if vertical > 0 else 'down'} {abs(vertical):.1f} m")
    else:
        #: 机位不动时,朝向的变化才是摇/俯仰。机位在动时朝向跟着变是移动的一部分,不另说。
        def heading(p: np.ndarray, t: np.ndarray) -> float:
            d = t - p
            return math.degrees(math.atan2(d[0], -d[2]))

        def pitch(p: np.ndarray, t: np.ndarray) -> float:
            d = (t - p) / max(float(np.linalg.norm(t - p)), 1e-6)
            return math.degrees(math.asin(max(-1.0, min(1.0, float(d[1])))))

        turn = (heading(p1, t1) - heading(p0, t0) + 180) % 360 - 180
        if abs(turn) > 3:
            parts.append(f"pan {'right' if turn > 0 else 'left'} {abs(turn):.0f}°")
        tilt = pitch(p1, t1) - pitch(p0, t0)
        if abs(tilt) > 3:
            parts.append(f"tilt {'up' if tilt > 0 else 'down'} {abs(tilt):.0f}°")
    if lens(end.fov) != lens(start.fov):
        parts.append(f"zoom to {lens(end.fov)}mm")
    if len(parts) == 1:
        parts.append("locked-off static camera")
    return ", ".join(parts)
