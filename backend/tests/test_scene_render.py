"""后端的白模渲染器:和工作台看到的是同一个构图。

它存在的理由是让工作流(跑在后端)也能拿 3D 白模当生成参考;而参考要有用,前提是它和用户
在工作台里摆的是**同一个镜头**。所以这里钉的是那些必须和前端一致的东西:机位的时间插值、
投影方向、遮挡、人物比例,以及室内机位时地面不会凭空消失。
"""

from __future__ import annotations

import shutil
import subprocess

import numpy as np
import pytest

from app.domain.scene_render import render_frame, render_shot_video
from app.domain.scene_render.meshes import meshes_for
from app.domain.scene_render.sampling import sample_camera, sample_object
from app.domain.scene_types import SceneContent, SceneObject, SceneShot

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def _scene(objects: list[dict], *, camera: dict | None = None, duration: float = 5) -> SceneContent:
    cam = {"id": "cam", "kind": "camera", "position": [0, 1, 5], "target": [0, 1, 0], "fov": 40, **(camera or {})}
    return SceneContent.model_validate({
        "objects": [*objects, cam],
        "shots": [{"id": "s", "duration": duration, "camera_id": "cam"}],
        "background": "#000000",
    })


def _pixel(image, x: float, y: float) -> np.ndarray:
    """按比例取像素(0..1),免得尺寸一改测试就全错位。"""
    width, height = image.size
    return np.asarray(image)[int(y * (height - 1)), int(x * (width - 1))].astype(int)


class Test机位和前端同一套插值:
    """对照 frontend/src/features/scenes/sceneGraph.ts 的 sampleCamera / sampleObject。"""

    def _camera(self) -> tuple[SceneObject, SceneShot]:
        camera = SceneObject(id="c", kind="camera", position=(0, 0, 10), target=(0, 0, 0), fov=40, track=[
            {"time": 0, "position": (0, 0, 10), "target": (0, 0, 0), "fov": 40},
            {"time": 4, "position": (4, 0, 10), "target": (0, 0, 0), "fov": 20},
        ])
        return camera, SceneShot(id="s", duration=5, camera_id="c", easing="smooth")

    def test_中点按_smoothstep_插值(self) -> None:
        camera, shot = self._camera()
        pose = sample_camera(camera, shot, 2)
        assert pose.position[0] == pytest.approx(2.0)  # smoothstep(0.5) = 0.5
        pose = sample_camera(camera, shot, 1)
        assert pose.position[0] == pytest.approx(4 * (0.25 * 0.25 * (3 - 0.5))), "四分之一处是 0.15625,不是线性的 1"

    def test_端点之外保持端点_时间夹在镜头时长里(self) -> None:
        camera, shot = self._camera()
        assert sample_camera(camera, shot, 4.5).fov == 20
        assert sample_camera(camera, shot, 99).position == (4, 0, 10)

    def test_空轨就是静止(self) -> None:
        still = SceneObject(id="b", kind="box", position=(1, 2, 3), rotation=(0, 45, 0))
        pose = sample_object(still, SceneShot(id="s", camera_id="c"), 3)
        assert pose.position == (1, 2, 3) and pose.rotation == (0, 45, 0)

    def test_关键帧没写的字段沿用静止值(self) -> None:
        obj = SceneObject(id="b", kind="box", rotation=(0, 90, 0), track=[
            {"time": 0, "position": (0, 0, 0)}, {"time": 2, "position": (2, 0, 0)},
        ])
        pose = sample_object(obj, SceneShot(id="s", camera_id="c", easing="linear"), 1)
        assert pose.position == pytest.approx((1, 0, 0)) and pose.rotation == (0, 90, 0)


class Test几何和工作台一样:
    def test_人物有多高就是多高(self) -> None:
        figure = SceneObject(id="f", kind="figure", parameters={"height": 1.7, "width": 0.42, "depth": 0.22})
        top = max(mesh.vertices[:, 1].max() for mesh in meshes_for(figure))
        bottom = min(mesh.vertices[:, 1].min() for mesh in meshes_for(figure))
        assert top == pytest.approx(1.7, abs=1e-6) and bottom == pytest.approx(0, abs=1e-6)

    def test_房间是地面加四面墙和两道门楣(self) -> None:
        room = SceneObject(id="r", kind="room")
        assert len(meshes_for(room)) == 9

    def test_楼梯有几级就是几块(self) -> None:
        stairs = SceneObject(id="s", kind="stairs", parameters={"steps": 6})
        assert len(meshes_for(stairs)) == 6

    def test_相机和分组不出现在画面里(self) -> None:
        assert meshes_for(SceneObject(id="c", kind="camera")) == []
        assert meshes_for(SceneObject(id="g", kind="group")) == []


class Test画出来的是那个镜头:
    def test_近的挡住远的(self) -> None:
        near = {"id": "near", "kind": "box", "position": [0, 0.5, 1], "parameters": {"width": 1, "height": 1, "depth": 1}, "color": "#ff0000"}
        far = {"id": "far", "kind": "box", "position": [0, 0, -2], "parameters": {"width": 3, "height": 3, "depth": 1}, "color": "#0000ff"}
        image = render_frame(_scene([far, near]), "s", 0, supersample=1).image
        r, g, b = _pixel(image, 0.5, 0.5)
        assert r > b, "前面那个红盒子应该挡住后面的蓝墙"

    def test_左右不反(self) -> None:
        """相机看向 -Z 时,+X 在画面右边 —— 反了的话,所有机位的构图都是镜像的。"""
        right = {"id": "right", "kind": "box", "position": [1.5, 0.5, 0], "parameters": {"width": 0.8, "height": 0.8, "depth": 0.8}, "color": "#00ff00"}
        image = render_frame(_scene([right]), "s", 0, supersample=1).image
        assert _pixel(image, 0.75, 0.5)[1] > 60, "物体在 +X,画面里应该在右半边"
        assert _pixel(image, 0.25, 0.5).sum() == 0, "左半边应该只有背景"

    def test_机位在房间里时地面照样在(self) -> None:
        """地板的大三角形有一半在相机背后 —— 不裁剪就整块丢掉,画面下半截只剩背景。"""
        room = {"id": "room", "kind": "room", "parameters": {"width": 8, "height": 3, "depth": 8}}
        image = render_frame(_scene([room], camera={"position": [0, 1.6, 2], "target": [0, 1.2, -2]}), "s", 0, supersample=1).image
        assert _pixel(image, 0.5, 0.95).sum() > 0, "画面底部应该是地板,不是背景"

    def test_运镜的两端画面不同(self) -> None:
        box = {"id": "b", "kind": "box", "position": [0, 0, 0], "color": "#ffffff"}
        content = _scene([box], camera={"track": [
            {"time": 0, "position": [0, 1, 8], "target": [0, 1, 0], "fov": 40},
            {"time": 5, "position": [0, 1, 3], "target": [0, 1, 0], "fov": 40},
        ]})
        start = np.asarray(render_frame(content, "s", 0, supersample=1).image)
        end = np.asarray(render_frame(content, "s", 5, supersample=1).image)
        assert (end.sum(axis=2) > 0).mean() > (start.sum(axis=2) > 0).mean(), "推近之后盒子应该占更大的画面"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_运镜参考视频和镜头一样长(tmp_path) -> None:
    content = _scene([{"id": "b", "kind": "box"}], duration=2)
    target = render_shot_video(content, "s", tmp_path / "move.mp4")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(target)],
        capture_output=True, text=True, check=True,
    )
    assert float(probe.stdout.strip()) == pytest.approx(2.0, abs=0.1)
