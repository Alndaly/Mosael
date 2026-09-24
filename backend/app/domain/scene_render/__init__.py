"""3D 场景 → 白模参考图 / 运镜参考视频。**在后端渲**。

为什么要有这一份:工作台的渲染器是浏览器里的 three.js,而工作流跑在后端 —— 此前"用 3D
白模给生成做参考"只能手动在工作台里点「生成素材」,整片自动生成的流程够不着它。于是自动
流程的每一镜只有一段文字提示词,构图、机位、人物站位全靠模型猜,六镜之间谁也对不上谁。

这里渲的是**白模**:几何、机位、光的方向与影子和工作台一致(见 sampling / meshes / raster
三个文件开头的对照说明),材质只取每个物体的颜色做漫反射。它是给图像/视频模型看"构图和
光从哪来"的,不是成片。

导入的模型由 `model_mesh` 读成三角形,调用方**把整份模型库一次装好传进来**(渲一段视频要
七十多帧,每帧重解一遍 GLB 是七十多倍的无用功);没传、或某一份读不了(Draco 压缩、面数超预算),
`skipped_models` 如实报出来,不假装它在。
"""

from __future__ import annotations

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.i18n import LocalizedError, tr
from app.domain.scene_render.meshes import FROM_FILE, meshes_for
from app.domain.scene_render.model_mesh import ModelLibrary
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


class SceneRenderError(LocalizedError, ValueError):
    """这个场景/镜头渲不了(镜头不存在、没有机位)。带文案 key(`sceneRenderErr_*`),按读的人的语言翻。"""


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


def _camera(content: SceneContent, shot: SceneShot, time: float) -> CameraPose:
    """这一刻的机位。**位置和看向点都是世界坐标,不管相机挂在哪个分组下** —— 工作台拍摄用的是一台
    独立的相机,直接按采样出来的 position / target 摆(SceneViewport 的 `pose()`),这里照同一个约定。"""
    camera = next((obj for obj in content.objects if obj.id == shot.camera_id), None)
    if camera is None or camera.kind != "camera":
        raise SceneRenderError("sceneRenderErr_shotNoCamera", shot=shot.name)
    return sample_camera(camera, shot, time)


def _triangles(content: SceneContent, world: dict[str, np.ndarray],
               models: ModelLibrary | None = None) -> tuple[Triangles, int]:
    objects = {obj.id: obj for obj in content.objects}
    corners, albedo, metal = [], [], []
    skipped = 0
    for obj in content.objects:
        if not _visible(obj, objects):
            continue
        parts = meshes_for(obj)
        if obj.kind in FROM_FILE:
            # 模型的几何在文件里。库里没有它(没传库,或那一份读不了)就记一笔跳过 ——
            # **少画一件道具必须说出来**,否则参考帧里那块是空的,而两边都不报错。
            parts = models.get(obj.model_id) if models else []
            if not parts:
                skipped += 1
                continue
        matrix = world[obj.id]
        color = hex_to_linear(obj.color)
        for mesh in parts:
            points = np.concatenate([mesh.vertices, np.ones((len(mesh.vertices), 1))], axis=1) @ matrix.T
            corners.append(points[:, :3][mesh.faces])
            # 图元自带颜色的(导入的模型)跟自己的,没有的跟物体 —— 见 meshes.Mesh.color。
            tint = color if mesh.color is None else mesh.color
            shine = obj.metalness if mesh.metalness is None else mesh.metalness
            albedo.append(np.repeat(tint[None, :], len(mesh.faces), axis=0))
            metal.append(np.full(len(mesh.faces), shine))
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
        raise SceneRenderError("sceneRenderErr_shotMissing", shot_id=shot_id)
    return shot


def render_frame(content: SceneContent, shot_id: str, time: float, *, supersample: int = STILL_SUPERSAMPLE,
                 models: ModelLibrary | None = None) -> RenderedFrame:
    """这个镜头在第 `time` 秒的白模画面。"""
    shot = find_shot(content, shot_id)
    return _render(content, shot, time, _camera(content, shot, time), FRAME_SIZES[shot.aspect], supersample, models)


#: 自由视角:不是哪个镜头的机位,而是「从哪个方向看整个场景」。给智能体改完摆位后自己检查用 ——
#: 镜头机位只拍得到构图里那一块,物体摆穿了、飘在半空、挡在门口,往往要从上面才看得出来。
#: 值是 (方位角, 仰角),度。顶视不取 90°:look_at 的上方向是 +Y,正对下方时退化。
FREE_VIEWS = {"overview": (45.0, 35.0), "top": (0.0, 88.0), "front": (0.0, 8.0), "side": (90.0, 8.0)}
FREE_VIEW_FOV = 40.0


def free_view_camera(content: SceneContent, view: str, shot: SceneShot, time: float = 0.0,
                     models: ModelLibrary | None = None) -> CameraPose:
    """把整个场景(`shot` 第 `time` 秒的样子)装进画面的一台相机。朝向由 `FREE_VIEWS` 给,距离按包围球算。

    模型库要一起传:取景按包围盒算,而导入的模型往往是场景里最大的那件东西 ——
    不算它的话,自由视角会把它切掉一半。"""
    if view not in FREE_VIEWS:
        raise SceneRenderError("sceneRenderErr_unknownView", view=view, options=", ".join(FREE_VIEWS))
    tris, _ = _triangles(content, _world_matrices(content, shot, time), models)
    if len(tris.corners):
        points = tris.corners.reshape(-1, 3)
        low, high = points.min(axis=0), points.max(axis=0)
    else:
        low, high = np.array([-2.0, 0.0, -2.0]), np.array([2.0, 2.0, 2.0])
    center = (low + high) / 2
    radius = max(0.5, float(np.linalg.norm(high - low)) / 2)
    azimuth, elevation = (math.radians(v) for v in FREE_VIEWS[view])
    direction = np.array([math.cos(elevation) * math.sin(azimuth), math.sin(elevation),
                          math.cos(elevation) * math.cos(azimuth)])
    distance = radius / math.sin(math.radians(FREE_VIEW_FOV) / 2) * 1.05
    position = center + direction * distance
    return CameraPose(position=tuple(float(v) for v in position), target=tuple(float(v) for v in center),
                      fov=FREE_VIEW_FOV)


def render_view(content: SceneContent, view: str, *, time: float = 0.0, shot_id: str = "",
                supersample: int = STILL_SUPERSAMPLE, models: ModelLibrary | None = None) -> RenderedFrame:
    """自由视角的白模画面(16:9)。`shot_id`(默认第一个镜头)只决定"此刻"物体动画走到哪 —— 不用它的机位。"""
    shot = find_shot(content, shot_id) if shot_id else content.shots[0]
    camera = free_view_camera(content, view, shot, time, models)
    return _render(content, shot, time, camera, FRAME_SIZES["16:9"], supersample, models)


def _render(content: SceneContent, shot: SceneShot, time: float, camera: CameraPose,
            size: tuple[int, int], supersample: int, models: ModelLibrary | None = None) -> RenderedFrame:
    world = _world_matrices(content, shot, time)
    tris, skipped = _triangles(content, world, models)
    width, height = size
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


def render_shot_video(content: SceneContent, shot_id: str, target: Path,
                      models: ModelLibrary | None = None) -> Path:
    """整个镜头的运镜参考视频(H.264 MP4)。物体有动画的也一起动。"""
    from app.core.child_process import run_logged
    from app.core.config import settings
    from app.core.text import blame_line

    shot = find_shot(content, shot_id)
    count = max(2, int(math.ceil(shot.duration * VIDEO_RENDER_FPS)) + 1)
    with tempfile.TemporaryDirectory(prefix="mosael-graybox-") as folder:
        for index in range(count):
            time = min(shot.duration, index / VIDEO_RENDER_FPS)
            render_frame(content, shot_id, time, supersample=1, models=models).image.save(Path(folder) / f"{index:05d}.png")
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
        detail = blame_line(completed.stderr or "", fallback="") or tr("sceneRenderErr_ffmpegNoReason")
        raise SceneRenderError("sceneRenderErr_videoEncodeFailed", detail=detail)
    return target


__all__ = [
    "FRAME_SIZES",
    "RenderedFrame",
    "SceneRenderError",
    "describe_camera_move",
    "FREE_VIEWS",
    "find_shot",
    "free_view_camera",
    "render_frame",
    "render_view",
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
