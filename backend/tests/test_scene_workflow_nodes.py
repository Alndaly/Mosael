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
