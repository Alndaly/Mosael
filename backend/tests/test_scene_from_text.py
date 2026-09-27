"""「按剧本搭 3D 场景」:3D 场景格的一种填法 —— 把剧本 / 分镜(文档、便签)连进场景格,搭出一个带机位和运镜的
白模场景,落进这一格。

写布景的 LLM 换成假的(交回一份布景);钉住的是:规矩和整片模板同一份、交给模型的是这段文字和道具清单、
建出来的场景带着镜头、画板上它挂在 3D 场景格上(不挂文档、便签)、搭好的场景落进这一格。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import Scene3D
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
from app.domain.workflows.executors import ai as ai_executors
from app.domain.workflows.executors.scenes import scene_from_text
from tests.test_scene_workflow_nodes import LAYOUT
from tests.util import fresh_client


@pytest.fixture()
def written(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_llm(db, scope, config):
        seen.update(config)
        return {"text": "", "json": seen.get("reply") or LAYOUT}

    monkeypatch.setattr(ai_executors, "llm", fake_llm)
    return seen


def _scope():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return SimpleNamespace(workspace_id=ws, id="board:b1", name="画板")


def test_照剧本搭出带镜头的场景_规矩和整片模板同一份(written) -> None:
    from app.domain.workflows.templates import blockout_rules

    scope = _scope()
    with SessionLocal() as db:
        out = scene_from_text(db, scope, {"text": "# 天台告白\n第一镜:小美推门走上天台……", "max_shots": 3, "aspect": "9:16"})
    assert out["shot_count"] == 1 and out["name"] == "天台告白", "没起名就取文字的第一行"
    assert blockout_rules(5, source="这段文字(没写明的尺寸、身高、光线按常识定)") in written["system"]
    assert "不超过 3 个镜头" in written["system"] and written["json_schema_name"] == "blockout_scene"
    assert "第一镜:小美推门走上天台" in written["prompt"] and "画幅:9:16" in written["prompt"]
    assert "可用的 3D 道具" in written["prompt"], "道具清单也交给它 —— 能用真道具就不用方块拼"
    with SessionLocal() as db:
        scene = db.get(Scene3D, out["scene_id"])
        assert scene is not None and scene.workspace_id == scope.workspace_id and scene.name == "天台告白"


def test_没有文字_镜头数夹在范围里(written) -> None:
    scope = _scope()
    with SessionLocal() as db:
        with pytest.raises(WorkflowDomainError) as caught:
            scene_from_text(db, scope, {"text": "  "})
        assert caught.value.key == "wfErr_sceneTextMissing"
        scene_from_text(db, scope, {"text": "一段话", "max_shots": 99})
    assert "不超过 12 个镜头" in written["system"]


def test_画板上是_3D_场景格的一种填法_剧本从连进来的文档便签接_搭好的场景落进这一格() -> None:
    """交出的是一个场景,剧本是参数不是原料 —— 和提示词出图挂在图片格上同一条判法,不挂在文档、便签上。"""
    from app.domain.boards.canvas import _canvas_with_delivered_result
    from app.domain.boards.tools import bindable_kinds, board_outputs
    from app.domain.boards.transforms import board_hosts, board_role, content_transform_gap, host_fields, output_kinds

    meta = NODE_TYPES["scene_from_text"]
    assert content_transform_gap(meta) is None
    assert board_role(meta) == "slot" and board_hosts(meta) == ("scene",) and host_fields(meta) == {}
    assert bindable_kinds("text", meta["config"]["text"]) == ["note", "document"], "剧本从连进来的文档、便签接"
    assert output_kinds(meta) == ["scene"]
    outputs = board_outputs(meta, {"scene_id": "sc-new", "shot_ids": ["s1"], "shot_count": 1, "name": "天台告白"})
    assert outputs == [{"type": "scene", "scene_id": "sc-new", "name": "天台告白"}]

    #: 已经有场景的格子按剧本重搭:新场景换进这一格,旧场景的缩略图摘掉(旧场景本身还在库里)。
    cell = {"id": "set", "kind": "scene", "x": 0, "y": 0, "scene_id": "sc-old", "asset_id": "thumb-old",
            "form": {"producer": "node:scene_from_text"}, "run": {"status": "running", "job_id": "j1"}}
    canvas = _canvas_with_delivered_result({"items": [cell], "edges": []}, item_id="set", job_id="j1", outputs=outputs,
                                           reason="", cancelled=False, succeeded=True, assets={})
    [filled] = canvas["items"]
    assert (filled["scene_id"], filled["text"], filled["run"]["status"]) == ("sc-new", "天台告白", "succeeded")
    assert "asset_id" not in filled


def test_空的_3D_场景格存得下_写了_id_照旧校验() -> None:
    from app.domain.boards import BoardDomainError, normalize_canvas

    empty = normalize_canvas({"items": [{"id": "set", "kind": "scene", "x": 0, "y": 0}], "edges": []})
    assert "scene_id" not in empty["items"][0]
    with pytest.raises(BoardDomainError):
        normalize_canvas({"items": [{"id": "set", "kind": "scene", "x": 0, "y": 0, "scene_id": "  "}], "edges": []})


def test_布景的空引用当作没有_不是非法_id(written) -> None:
    """严格模式的结构化输出要求每一格都在,用不上的父级、模型 id 写空字符串 —— 此前建场景时被当成非法 id 拒了
    (用户撞上:「objects.0.parent_id: String should have at least 1 character」)。"""
    from tests.test_scene_workflow_nodes import LAYOUT as BASE

    strict = {**BASE, "objects": [{**one, "parent_id": "", "model_id": ""} for one in BASE["objects"]]}
    written["reply"] = strict

    scope = _scope()
    with SessionLocal() as db:
        out = scene_from_text(db, scope, {"text": "一个女孩在雪山脚下的草原上跑步"})
    assert out["shot_count"] == 1
