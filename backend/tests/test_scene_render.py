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


def test_分组里的相机照样按世界坐标拍() -> None:
    """工作台拍摄用的是一台独立的相机,直接按 position / target 摆(SceneViewport 的 pose())——
    相机挂在哪个分组下都不影响它拍到什么。套上分组变换的话,同一个镜头在两边是两个构图。"""
    box = {"id": "b", "kind": "box", "position": [0, 0, 0], "color": "#ffffff"}
    loose = render_frame(_scene([box]), "s", 0, supersample=1).image
    rig = {"id": "rig", "kind": "group", "position": [30, 0, 0]}
    grouped = SceneContent.model_validate({
        "objects": [box, rig, {"id": "cam", "kind": "camera", "parent_id": "rig", "position": [0, 1, 5], "target": [0, 1, 0], "fov": 40}],
        "shots": [{"id": "s", "duration": 5, "camera_id": "cam"}],
        "background": "#000000",
    })
    assert np.array_equal(np.asarray(loose), np.asarray(render_frame(grouped, "s", 0, supersample=1).image))


class Test自由视角给智能体自己检查:
    """view_scene 的那几个角度:改完摆位后从上面、侧面看一眼,而不是凭数字想象。"""

    def test_俯瞰把远处的物体也装进画面(self) -> None:
        near = {"id": "a", "kind": "box", "position": [0, 0, 0], "color": "#ff0000"}
        far = {"id": "b", "kind": "box", "position": [12, 0, -8], "color": "#00ff00"}
        from app.domain.scene_render import render_view

        image = np.asarray(render_view(_scene([near, far]), "overview", supersample=1).image).astype(int)
        assert (image[..., 0] > 80).any() and (image[..., 1] > 80).any(), "两个盒子都该在画面里"

    def test_顶视图看得出左右前后(self) -> None:
        """顶视时 +X 仍在画面右边 —— 布局图左右颠倒的话,模型会照着反的去挪。"""
        from app.domain.scene_render import render_view

        left = {"id": "l", "kind": "box", "position": [-3, 0, 0], "color": "#ff0000"}
        right = {"id": "r", "kind": "box", "position": [3, 0, 0], "color": "#0000ff"}
        image = np.asarray(render_view(_scene([left, right]), "top", supersample=1).image).astype(int)
        red = np.argwhere(image[..., 0] > image[..., 2] + 60)[:, 1].mean()
        blue = np.argwhere(image[..., 2] > image[..., 0] + 60)[:, 1].mean()
        assert red < blue

    def test_默认看第一个镜头的机位和俯瞰(self) -> None:
        from types import SimpleNamespace

        from app.domain.scenes import view_scene

        content = _scene([{"id": "b", "kind": "box"}]).model_dump(mode="json")
        # 场景里没有导入模型,所以取模型库那一步根本不查库(见 scenes.model_library 的早返回)。
        out = view_scene(None, SimpleNamespace(content=content, revision=3), views=[])
        assert [one["view"] for one in out["images"]] == ["shot", "overview"]
        assert out["shot_id"] == "s" and out["images"][0]["mime_type"] == "image/jpeg"

    def test_不认识的视角直接说可选项(self) -> None:
        from types import SimpleNamespace

        from app.domain.scenes import SceneDomainError, view_scene

        content = _scene([]).model_dump(mode="json")
        with pytest.raises(SceneDomainError, match="overview"):
            view_scene(None, SimpleNamespace(content=content, revision=1), views=["fisheye"])


def test_看图工具返回的是图片块_通道上拆成文字和图片() -> None:
    """模型要**看见**画面:MCP 客户端收到标准图片块;HTTP 通道拆成 result + images,
    不能把几十万字符的 base64 塞进 JSON 让模型去读。"""
    from mcp.types import ImageContent, TextContent

    import mcp_server
    from app.api.routes.agent_tools import _as_payload

    blocks = mcp_server._with_images({"revision": 2, "images": [{"view": "top", "mime_type": "image/jpeg", "data": "QQ=="}]})
    assert isinstance(blocks[0], TextContent) and isinstance(blocks[1], ImageContent)
    assert "QQ==" not in blocks[0].text
    assert _as_payload(blocks) == {"result": {"revision": 2, "image_views": ["top"]},
                                   "images": [{"mime_type": "image/jpeg", "data": "QQ=="}]}
    assert _as_payload({"plain": 1}) == {"result": {"plain": 1}}
