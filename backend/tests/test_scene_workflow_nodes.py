"""工作流里的 3D 白模:搭场景、渲参考。

这两个节点让整片自动生成用上 3D 白模。钉住的是:布景建成的是一个**真正的** 3D 场景(能在
工作台里打开);布景错了当场说错在哪,而不是替它修一个"看起来合理"的值;渲出来的是素材、
归在本工作区;以及镜头语言是从机位轨迹算出来的。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Scene3D, Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client

LAYOUT = {
    "objects": [
        {"id": "room", "kind": "room", "parameters": {"width": 8, "height": 3, "depth": 8}},
        {"id": "hero", "name": "主角", "kind": "figure", "position": [0, 0, -1], "color": "#c0504d"},
        {
            "id": "cam-1", "kind": "camera", "position": [0, 1.6, 3], "target": [0, 1.4, -1], "fov": 40,
            #: 故意倒着写:LLM 常按叙述顺序写关键帧,节点负责排好序。
            "track": [
                {"time": 5, "position": [0, 1.6, 1], "target": [0, 1.4, -1], "fov": 40},
                {"time": 0, "position": [0, 1.6, 3], "target": [0, 1.4, -1], "fov": 40},
            ],
        },
    ],
    "shots": [{"id": "shot-1", "name": "推近主角", "duration": 5, "camera_id": "cam-1"}],
}


def _workflow() -> Workflow:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="白模测试", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        db.expunge(workflow)
        return workflow


def _run(node_type: str, workflow: Workflow, config: dict) -> dict:
    with SessionLocal() as db:
        return get_executor(node_type)(db, db.get(Workflow, workflow.id), config)


def test_布景建成一个真正的_3D_场景() -> None:
    workflow = _workflow()
    out = _run("scene_create", workflow, {"name": "教室", "layout": LAYOUT})
    assert out["shot_ids"] == ["shot-1"] and out["shot_count"] == 1
    with SessionLocal() as db:
        scene = db.get(Scene3D, out["scene_id"])
        assert scene.workspace_id == workflow.workspace_id and scene.name == "教室"
        track = next(o for o in scene.content["objects"] if o["id"] == "cam-1")["track"]
        assert [frame["time"] for frame in track] == [0, 5], "关键帧要按时间排好序"


def test_布景也可以是一段_JSON_文本() -> None:
    import json

    out = _run("scene_create", _workflow(), {"layout": json.dumps(LAYOUT)})
    assert out["shot_count"] == 1


def test_布景错了说出错在哪_不替它修() -> None:
    """镜头指向一台不存在的相机:此前没有这个节点;有了之后,错误要落在"哪一项"上。"""
    broken = {**LAYOUT, "shots": [{"id": "s", "duration": 5, "camera_id": "no-such-camera"}]}
    with pytest.raises(WorkflowDomainError) as caught:
        _run("scene_create", _workflow(), {"layout": broken})
    assert caught.value.key == "wfErr_sceneLayoutInvalid"
    assert "camera" in str(caught.value)


def test_渲出首尾静帧和镜头语言() -> None:
    workflow = _workflow()
    scene_id = _run("scene_create", workflow, {"layout": LAYOUT})["scene_id"]
    out = _run("scene_render", workflow, {"scene_id": scene_id, "shot_id": "shot-1", "render": "stills"})
    assert out["first_frame_asset_id"] and out["last_frame_asset_id"] and not out["video_asset_id"]
    with SessionLocal() as db:
        first = db.get(Asset, out["first_frame_asset_id"])
        assert first.workspace_id == workflow.workspace_id and first.source == "graybox"
    assert "dolly in 2.0 m" in out["camera_move"], "镜头语言是从机位轨迹算的:从 3 米推到 1 米"


def test_别的工作区的场景渲不了() -> None:
    other = _workflow()
    scene_id = _run("scene_create", other, {"layout": LAYOUT})["scene_id"]
    with pytest.raises(WorkflowDomainError) as caught:
        _run("scene_render", _workflow(), {"scene_id": scene_id, "shot_id": "shot-1"})
    assert caught.value.key == "wfErr_sceneNotInWorkspace"


def test_没有这个镜头时说清楚() -> None:
    workflow = _workflow()
    scene_id = _run("scene_create", workflow, {"layout": LAYOUT})["scene_id"]
    with pytest.raises(WorkflowDomainError) as caught:
        _run("scene_render", workflow, {"scene_id": scene_id, "shot_id": "shot-9"})
    assert caught.value.key == "wfErr_sceneRenderFailed"


def _import_glb(workspace_id: str, name: str, tmp_path, **params) -> str:
    """往这个工作区里收一份真 GLB,返回 model_id。用后端自己的写入器造,读的那一侧和写的对表。"""
    from app.domain.scene_render import find_shot
    from app.domain.scene_render.gltf import write_glb
    from app.domain.scene_types import SceneContent
    from app.domain.scenes import import_model

    content = SceneContent.model_validate({
        "objects": [{"id": "b", "kind": "box", "parameters": params or {"width": 2, "height": 1, "depth": 3}},
                    {"id": "cam", "kind": "camera", "position": [0, 2, 6], "target": [0, 1, 0]}],
        "shots": [{"id": "s", "camera_id": "cam", "duration": 2}],
    })
    target = tmp_path / f"{name}.glb"
    write_glb(content, find_shot(content, "s"), target)
    with SessionLocal() as db, target.open("rb") as stream:
        return import_model(db, workspace_id, name, stream).id


class Test可用的3D道具:
    """布景师要知道**有哪些道具能摆、各自多大**。

    没有这份清单时,设计布景的那个 LLM 不可能凭空写出一串模型 id —— 于是自动流程里的布景
    永远只能是基本体拼的,在 Blender 里建好的产品模型进不去。
    """

    def test_尺寸是量出来的_不是填的(self, tmp_path) -> None:
        # "这个模型多大"只有文件自己知道。让人在节点里手填等于请他抄一遍,抄错了没人发现。
        workflow = _workflow()
        _import_glb(workflow.workspace_id, "产品主体", tmp_path, width=2, height=1, depth=3)
        out = _run("scene_props", workflow, {"model_ids": ""})
        assert out["count"] == 1
        assert "产品主体" in out["catalog"]
        assert "宽 2.00 × 高 1.00 × 深 3.00 米" in out["catalog"], out["catalog"]

    def test_留空就是全部_勾了就只给勾中的(self, tmp_path) -> None:
        workflow = _workflow()
        first = _import_glb(workflow.workspace_id, "道具甲", tmp_path)
        _import_glb(workflow.workspace_id, "道具乙", tmp_path)
        assert _run("scene_props", workflow, {"model_ids": ""})["count"] == 2
        picked = _run("scene_props", workflow, {"model_ids": first})
        assert picked["model_ids"] == [first] and "道具乙" not in picked["catalog"]

    def test_勾选也可以是上游交来的一列_id(self, tmp_path) -> None:
        """model_ids 是模板字段,整串引用上游(`{{筛选.model_ids}}`)时插值保留列表原样。

        此前按字符串拆逗号:列表被 str() 成 `['…']`,一个都对不上,清单里只剩一句
        "指定的模型不在这个工作区里" —— 而它们明明就在。
        """
        workflow = _workflow()
        first = _import_glb(workflow.workspace_id, "道具甲", tmp_path)
        _import_glb(workflow.workspace_id, "道具乙", tmp_path)
        picked = _run("scene_props", workflow, {"model_ids": [first]})
        assert picked["model_ids"] == [first], picked["catalog"]

    def test_一件都没有时明说_而不是交一份空白(self) -> None:
        # 空白清单会让布景师以为自己漏看了什么。说清楚"这次只用基本体"。
        out = _run("scene_props", _workflow(), {"model_ids": ""})
        assert out["count"] == 0 and "只用基本体" in out["catalog"]

    def test_读不了的不进清单_但要说一声(self, tmp_path) -> None:
        """列出来只会让布景师摆上一件渲不出来的东西,而那时画面里是个空位。"""
        import json
        import struct

        from app.domain.scenes import model_file
        from app.db.models import Scene3DModel

        workflow = _workflow()
        good = _import_glb(workflow.workspace_id, "好道具", tmp_path)
        bad = _import_glb(workflow.workspace_id, "压缩过的道具", tmp_path)
        with SessionLocal() as db:
            path = model_file(db.get(Scene3DModel, bad))
        raw = path.read_bytes()
        length, _ = struct.unpack_from("<II", raw, 12)
        doc = json.loads(raw[20:20 + length].decode())
        doc["extensionsRequired"] = ["KHR_draco_mesh_compression"]
        payload = json.dumps(doc, separators=(",", ":")).encode()
        payload += b" " * (-len(payload) % 4)
        rest = raw[20 + length:]
        path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload) + len(rest))
                         + struct.pack("<II", len(payload), 0x4E4F534A) + payload + rest)

        out = _run("scene_props", workflow, {"model_ids": ""})
        assert out["model_ids"] == [good]
        assert "压缩过的道具" in out["catalog"] and "Draco" in out["catalog"]

    def test_指定了一份不在这个工作区的_跳过并说明(self) -> None:
        out = _run("scene_props", _workflow(), {"model_ids": "deadbeef"})
        assert out["count"] == 0 and "不在这个工作区里" in out["catalog"]
