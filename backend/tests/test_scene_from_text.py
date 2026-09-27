"""「按文字搭 3D 场景」:剧本 / 分镜连进便签或文档格,搭出一个带机位和运镜的白模场景,落成右边一格 3D 场景格。

写布景的 LLM 换成假的(交回一份布景);钉住的是:规矩和整片模板同一份、交给模型的是这段文字和道具清单、
建出来的场景带着镜头、画板上它是便签和文档格的能力、产出落成一格挂着渲白模的 3D 场景格。
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
        return {"text": "", "json": LAYOUT}

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


def test_画板上是便签和文档格的能力_产出落成一格挂着渲白模的_3D_场景格() -> None:
    from app.domain.boards.canvas import _derived_item
    from app.domain.boards.tools import board_outputs
    from app.domain.boards.transforms import board_hosts, board_role, content_transform_gap, output_kinds

    meta = NODE_TYPES["scene_from_text"]
    assert content_transform_gap(meta) is None
    assert board_role(meta) == "ability" and board_hosts(meta) == ("note", "document")
    assert output_kinds(meta) == ["scene"]
    outputs = board_outputs(meta, {"scene_id": "sc-1", "shot_ids": ["s1"], "shot_count": 1, "name": "天台告白"})
    assert outputs == [{"type": "scene", "scene_id": "sc-1", "name": "天台告白"}]
    assert _derived_item(outputs[0], {}) == {"kind": "scene", "scene_id": "sc-1", "text": "天台告白",
                                            "form": {"producer": "scene_render"}}
