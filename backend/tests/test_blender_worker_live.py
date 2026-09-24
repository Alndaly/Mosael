"""智能体的四个 Blender 操作,在**真的** Blender 里跑一遍。

worker.py 跑在别人的 Blender 里,单测替身测不出 bpy API 用错(属性改名、枚举值不存在、上下文
不对)。所以这里起一个**独立的无界面 Blender 进程**(不碰用户开着的那个),把 worker 原样喂进去,
按 bridge 的同一种方式调用、按同一种方式读结果文件。

本机没装 Blender 就跳过(CI 上没有)。路径可用 MOSAEL_TEST_BLENDER 指定。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.domain.blender.scripts import command

CANDIDATES = [os.environ.get("MOSAEL_TEST_BLENDER", ""), shutil.which("blender") or "",
              "/Applications/Blender.app/Contents/MacOS/Blender"]
BLENDER = next((path for path in CANDIDATES if path and Path(path).is_file()), "")

pytestmark = pytest.mark.skipif(not BLENDER, reason="Blender not installed")


def _run(tmp_path: Path, operation: str, payload: dict, *, setup: str = "") -> dict:
    """在一个新的无界面 Blender 里:清空默认场景 → 跑 setup → 跑一个 worker 操作 → 读结果。"""
    result = tmp_path / f"{operation}.json"
    script = tmp_path / f"{operation}.py"
    script.write_text(
        "import bpy\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        + setup + "\n"
        + command(operation, {**payload, "result_path": str(result)}),
        encoding="utf-8",
    )
    completed = subprocess.run([BLENDER, "--background", "--factory-startup", "--python-exit-code", "1",
                                "--python", str(script)], capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    return json.loads(result.read_text(encoding="utf-8"))


CUBE = "bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1)); bpy.context.object.name = 'Pillar'"


def test_inspect_列出物体和网格细节(tmp_path) -> None:
    out = _run(tmp_path, "inspect", {}, setup=CUBE)
    pillar = next(obj for obj in out["objects"] if obj["name"] == "Pillar")
    assert pillar["type"] == "MESH" and pillar["dimensions"] == [2.0, 2.0, 2.0] and pillar["faces"] == 6


def test_execute_跑建模代码_错误带回_traceback(tmp_path) -> None:
    code = ("bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=3, location=(1, 0, 1.5))\n"
            "bpy.context.object.name = 'Column'\n"
            "mod = bpy.context.object.modifiers.new('Bevel', 'BEVEL')\n"
            "print('made', bpy.context.object.name)\n"
            "output = [o.name for o in bpy.context.scene.objects]")
    out = _run(tmp_path, "execute", {"code": code})
    assert out["error"] is None and out["output"] == ["Column"] and "made Column" in out["printed"]

    broken = _run(tmp_path, "execute", {"code": "bpy.data.objects['Nope'].location.x = 1"})
    assert "KeyError" in broken["error"]


def test_look_渲出图片且还原渲染设置(tmp_path) -> None:
    setup = CUBE + "\nbpy.context.scene.render.engine = 'CYCLES'\nbpy.context.scene.render.resolution_x = 123"
    folder = tmp_path / "shots"
    folder.mkdir()
    check = ("\nimport json\nassert bpy.context.scene.render.engine == 'CYCLES', bpy.context.scene.render.engine"
             "\nassert bpy.context.scene.render.resolution_x == 123"
             "\nassert 'mosael-look' not in bpy.data.objects")
    result = tmp_path / "look.json"
    script = tmp_path / "look.py"
    script.write_text("import bpy\nbpy.ops.wm.read_factory_settings(use_empty=True)\n" + setup + "\n"
                      + command("look", {"views": [{"name": "overview", "azimuth": 35, "elevation": 30},
                                                   {"name": "top", "azimuth": 0, "elevation": 89}],
                                         "objects": [], "shading": "solid",
                                         "folder": str(folder), "result_path": str(result)}) + check, encoding="utf-8")
    completed = subprocess.run([BLENDER, "--background", "--factory-startup", "--python-exit-code", "1",
                                "--python", str(script)], capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    out = json.loads(result.read_text(encoding="utf-8"))
    assert [one["view"] for one in out["images"]] == ["overview", "top"]
    assert all(Path(one["path"]).stat().st_size > 1000 for one in out["images"])


def test_发送_把后端生成的场景_连同导入的模型一起摆进_Blender(tmp_path) -> None:
    """端到端:后端生成 GLB → Blender 里出现同样的物体、分组、镜头;导入的模型挂在它的锚点下。"""
    from app.domain.scene_render import find_shot
    from app.domain.scene_render.gltf import write_glb
    from app.domain.scene_types import SceneContent

    model = tmp_path / "prop.glb"
    _run(tmp_path, "export", {"objects": [], "output_path": str(model)},
         setup="bpy.ops.mesh.primitive_cone_add(location=(0, 0, 1)); bpy.context.object.name = 'Prop'")

    content = SceneContent.model_validate({
        "objects": [
            {"id": "g", "kind": "group", "name": "展厅", "position": [3, 0, 0]},
            {"id": "room", "kind": "room", "name": "房间", "parent_id": "g",
             "parameters": {"width": 6, "height": 3, "depth": 5}},
            {"id": "m", "kind": "model", "name": "道具", "model_id": "mdl", "position": [-2, 0, 0]},
            {"id": "cam", "kind": "camera", "position": [0, 1.6, 7], "target": [0, 1.2, 0], "fov": 45},
        ],
        "shots": [{"id": "s", "name": "主镜", "camera_id": "cam", "duration": 3}],
    })
    scene_glb = tmp_path / "scene.glb"
    written = write_glb(content, find_shot(content, "s"), scene_glb)
    assert written["models"] == [{"object_id": "m", "model_id": "mdl"}]

    from app.domain.blender.bridge import shots_with_frames

    snapshot = {"id": "sc", "name": "展厅", "content": {**content.model_dump(mode="json"),
                                                        "shots": shots_with_frames(content.model_dump(mode="json"))}}
    out = _run(tmp_path, "send", {
        "snapshot": snapshot, "shot_id": "s", "transfer_id": "t1", "input_path": str(scene_glb),
        "models": [{"object_id": "m", "name": "道具", "path": str(model)}],
        "blend_path": str(tmp_path / "scene.blend"),
    })
    assert out["warnings"] == [] and out["camera_count"] == 1
    assert (tmp_path / "scene.blend").is_file()

    listing = _run(tmp_path, "inspect", {}, setup=(
        "bpy.ops.wm.open_mainfile(filepath=%r)\n" % str(tmp_path / "scene.blend")
        + "bpy.context.window.scene = next(s for s in bpy.data.scenes if s.get('mosael_transfer_id') == 't1')"))
    by_name = {obj["name"]: obj for obj in listing["objects"]}
    assert by_name["房间"]["parent"] == "展厅"
    assert by_name["房间"]["dimensions"] == [6.15, 5.15, 3.08], "米制尺寸原样过去(含墙厚)"
    assert by_name["Prop"]["parent"] == "道具", "导入的模型挂在它的锚点下"
    assert [o for o in listing["objects"] if o["type"] == "CAMERA"], "镜头成了真正的 Blender 相机"


def test_export_只导出点名的物体(tmp_path) -> None:
    setup = CUBE + "\nbpy.ops.mesh.primitive_uv_sphere_add(location=(4, 0, 1)); bpy.context.object.name = 'Ball'"
    target = tmp_path / "model.glb"
    out = _run(tmp_path, "export", {"objects": ["Pillar"], "output_path": str(target)}, setup=setup)
    assert out["object_count"] == 1 and target.read_bytes()[:4] == b"glTF"
    assert b"Ball" not in target.read_bytes() and b"Pillar" in target.read_bytes()


NATIVE = """
import math
from mathutils import Vector
scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
scene.render.fps, scene.frame_start, scene.frame_end = 24, 1, 24
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
def cam(name, location, look=None):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)
    obj.location = location
    if look is not None:
        obj.rotation_euler = (Vector(look) - Vector(location)).to_track_quat('-Z', 'Y').to_euler()
    return obj
scene.camera = cam('Aimed', (0, -10, 1), look=(0, 0, 1))
focused = cam('Focused', (0, -10, 1), look=(0, 0, 1))
focused.data.dof.use_dof, focused.data.dof.focus_distance = True, 6
target = bpy.data.objects.new('Target', None)
target.location = (3, 0, 1)
scene.collection.objects.link(target)
tracked = cam('Tracked', (3, -8, 1))
constraint = tracked.constraints.new('TRACK_TO')
constraint.target, constraint.track_axis, constraint.up_axis = target, 'TRACK_NEGATIVE_Z', 'UP_Y'
cam('Ortho', (0, -10, 1), look=(0, 0, 1)).data.type = 'ORTHO'
cam('Top', (0, 0, 10))
dolly = cam('Dolly', (0, -12, 1), look=(0, 0, 1))
dolly.keyframe_insert('location', frame=1)
dolly.location.y = -6
dolly.keyframe_insert('location', frame=25)
scene.frame_set(7)
def lamp(name, kind, location, rotation=(0, 0, 0), **settings):
    data = bpy.data.lights.new(name, kind)
    for key, value in settings.items():
        setattr(data, key, value)
    obj = bpy.data.objects.new(name, data)
    obj.location, obj.rotation_euler = location, rotation
    scene.collection.objects.link(obj)
lamp('Light', 'POINT', (4.08, 1.01, 5.90), energy=1000)
lamp('Sun', 'SUN', (0, 0, 10), rotation=(math.radians(35), 0, 0), energy=4)
lamp('Spot', 'SPOT', (0, 0, 4), energy=500, spot_size=math.radians(45))
"""


def _close(a, b, tolerance=1e-3):
    return all(abs(x - y) < tolerance for x, y in zip(a, b))


def test_pull_取回原生相机和灯光(tmp_path) -> None:
    """一个纯 Blender 的工程:相机按用户表达过的意图推出"看向哪里",灯光按类型换算;GLB 里不再带灯。"""
    import math

    from app.domain.blender.bridge import native_cameras, native_lights

    glb = tmp_path / "pulled.glb"
    out = _run(tmp_path, "pull", {"output_path": str(glb)}, setup=NATIVE)
    cameras = {c["name"]: c for c in out["cameras"]}
    assert [c["name"] for c in out["cameras"]] == ["Aimed", "Dolly", "Focused", "Tracked"], "活动相机在前,其余按名字"
    assert {c["aspect"] for c in out["cameras"]} == {"16:9"}
    # Blender (x, y, z) → Mosael (x, z, -y)。
    aimed = cameras["Aimed"]["frames"]
    assert len(aimed) == 1 and _close(aimed[0]["position"], [0, 1, 10])
    assert _close(aimed[0]["target"], [0, 1, 1]), "射线打在立方体正面(y = -1)"
    assert abs(aimed[0]["fov"] - math.degrees(2 * math.atan(18 / 50 / (16 / 9)))) < 1e-3
    assert _close(cameras["Focused"]["frames"][0]["target"], [0, 1, 4]), "开着景深时,对焦距离先于射线"
    assert _close(cameras["Tracked"]["frames"][0]["target"], [3, 1, 0]), "Track To 的目标就是看向哪里"
    dolly = cameras["Dolly"]
    assert dolly["duration"] == 1 and len(dolly["frames"]) == 25
    assert _close(dolly["frames"][0]["position"], [0, 1, 12]) and _close(dolly["frames"][-1]["position"], [0, 1, 6])
    assert _close(dolly["frames"][0]["target"], [0, 1, 1])
    # Blender 那边只回「是哪一种」和参数,句子由后端按语言翻(bridge.render_warnings)。
    assert sorted((w["key"], w["params"]["name"]) for w in out["warnings"] if w["key"].startswith("blenderWarn_camera")) == [
        ("blenderWarn_cameraNotPerspective", "Ortho"),
        ("blenderWarn_cameraRolled", "Top")]
    _, shots, _ = native_cameras(out["cameras"])
    assert [s["name"] for s in shots] == ["Aimed", "Dolly", "Focused", "Tracked"]

    lights = {light["name"]: light for light in out["lights"]}
    assert _close(lights["Light"]["position"], [4.08, 5.9, -1.01]) and lights["Light"]["power"] == 1000
    assert lights["Spot"]["type"] == "SPOT" and abs(lights["Spot"]["spot_size"] - 45) < 1e-3
    points, lighting, _ = native_lights(out["lights"], 10)
    assert [p["name"] for p in points] == ["Light", "Spot"]
    # 太阳绕 X 转 35°:光线斜着往 +Y 下方打,于是光源在 -Y 那一侧(Mosael 的 +Z,方位角 0)、仰角 55°。
    assert (round(lighting.azimuth, 3) % 360, round(lighting.elevation, 3)) == (0, 55)
    assert b"KHR_lights_punctual" not in glb.read_bytes(), "灯成了 Mosael 的灯,模型里再带一份就亮两次"


def test_发送再取回_机位和灯光不变(tmp_path) -> None:
    """Mosael 发过去的场景,在 Blender 里原样取回:机位靠自带的目标距离,灯光按发送时的换算反算。"""
    from app.domain.blender.bridge import native_cameras, native_lights, shots_with_frames
    from app.domain.scene_render import find_shot
    from app.domain.scene_render.gltf import write_glb
    from app.domain.scene_types import SceneContent

    content = SceneContent.model_validate({
        "objects": [
            {"id": "floor", "kind": "box", "name": "地台", "parameters": {"width": 6, "height": .2, "depth": 6}},
            {"id": "lamp", "kind": "light", "name": "台灯", "position": [1, 3, 2], "color": "#ffcc88", "intensity": 30},
            {"id": "cam", "kind": "camera", "name": "主机位", "position": [0, 1.6, 7], "target": [0, 1.2, 0], "fov": 45},
        ],
        "shots": [{"id": "s", "name": "主镜", "camera_id": "cam", "duration": 3}],
    })
    scene_glb = tmp_path / "scene.glb"
    write_glb(content, find_shot(content, "s"), scene_glb)
    dumped = content.model_dump(mode="json")
    snapshot = {"id": "sc", "name": "往返", "content": {**dumped, "shots": shots_with_frames(dumped)}}
    _run(tmp_path, "send", {"snapshot": snapshot, "shot_id": "s", "transfer_id": "t1", "input_path": str(scene_glb),
                            "models": [], "blend_path": str(tmp_path / "scene.blend")})

    out = _run(tmp_path, "pull", {"output_path": str(tmp_path / "pulled.glb")}, setup=(
        "bpy.ops.wm.open_mainfile(filepath=%r)\n" % str(tmp_path / "scene.blend")
        + "bpy.context.window.scene = next(s for s in bpy.data.scenes if s.get('mosael_transfer_id') == 't1')"))
    objects, shots, warnings = native_cameras(out["cameras"])
    assert warnings == [] and [s["name"] for s in shots] == ["主镜"]
    camera = objects[0]
    assert camera["track"] == [], "没动过的机位收成一帧"
    assert _close(camera["position"], [0, 1.6, 7]) and _close(camera["target"], [0, 1.2, 0])
    assert abs(camera["fov"] - 45) < 1e-3
    lights, lighting, notes = native_lights(out["lights"], 10)
    assert notes == [] and lighting is None
    assert lights[0]["name"] == "台灯" and lights[0]["color"] == "#ffcc88"
    assert abs(lights[0]["intensity"] - 30) < 1e-3 and _close(lights[0]["position"], [1, 3, 2])
