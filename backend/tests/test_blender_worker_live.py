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
                      + command("look", {"views": ["overview", "top"], "objects": [], "shading": "solid",
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
