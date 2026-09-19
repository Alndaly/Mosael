"""某一时刻,物体和机位在哪。**逐行对照前端 `features/scenes/sceneGraph.ts`**。

两边必须给出同一个答案:用户在工作台里看着某一秒的构图调好了机位,工作流在后端渲出来的
那一帧得是同一个构图,否则"白模参考"参考的是另一个镜头。规则都在那边的注释里:

- 空轨就是静止,直接用物体自己的姿态;
- 时间先夹在 `[0, shot.duration]`;
- 落在两档之间按镜头的缓动插值(`smooth` = smoothstep),端点之外保持端点;
- 关键帧没写的字段沿用静止值。

`tests/test_scene_render.py` 用前端同一组数字钉着这几条。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.scene_types import Keyframe, SceneObject, SceneShot

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class CameraPose:
    position: Vec3
    target: Vec3
    fov: float


@dataclass(frozen=True)
class ObjectPose:
    position: Vec3
    rotation: Vec3
    scale: Vec3


def _mix(a: Vec3, b: Vec3, u: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u)


def _bracket(track: list[Keyframe], shot: SceneShot, time: float) -> tuple[Keyframe, Keyframe, float] | Keyframe:
    """找到 t 所在的那一段;端点之外返回那一档本身。"""
    t = max(0.0, min(time, shot.duration))
    after = next((i for i, frame in enumerate(track) if frame.time > t), -1)
    if after < 0:
        return track[-1]
    if after == 0:
        return track[0]
    a, b = track[after - 1], track[after]
    u = (t - a.time) / (b.time - a.time)
    if shot.easing == "smooth":
        u = u * u * (3 - 2 * u)
    return a, b, u


def sample_camera(camera: SceneObject, shot: SceneShot, time: float) -> CameraPose:
    still = CameraPose(tuple(camera.position), tuple(camera.target), camera.fov)
    if not camera.track:
        return still

    def at(frame: Keyframe) -> CameraPose:
        return CameraPose(
            tuple(frame.position),
            tuple(frame.target) if frame.target is not None else still.target,
            frame.fov if frame.fov is not None else still.fov,
        )

    found = _bracket(camera.track, shot, time)
    if isinstance(found, Keyframe):
        return at(found)
    a, b, u = found
    pa, pb = at(a), at(b)
    return CameraPose(_mix(pa.position, pb.position, u), _mix(pa.target, pb.target, u), pa.fov + (pb.fov - pa.fov) * u)


def sample_object(obj: SceneObject, shot: SceneShot, time: float) -> ObjectPose:
    still = ObjectPose(tuple(obj.position), tuple(obj.rotation), tuple(obj.scale))
    if not obj.track:
        return still

    def at(frame: Keyframe) -> ObjectPose:
        return ObjectPose(
            tuple(frame.position),
            tuple(frame.rotation) if frame.rotation is not None else still.rotation,
            tuple(frame.scale) if frame.scale is not None else still.scale,
        )

    found = _bracket(obj.track, shot, time)
    if isinstance(found, Keyframe):
        return at(found)
    a, b, u = found
    pa, pb = at(a), at(b)
    return ObjectPose(
        _mix(pa.position, pb.position, u), _mix(pa.rotation, pb.rotation, u), _mix(pa.scale, pb.scale, u)
    )
