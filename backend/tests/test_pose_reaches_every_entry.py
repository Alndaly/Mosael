"""`@` 姿势怎么发(机位、是否当参考图)要从**每一个生成入口**交进漏斗(ADR 0091 §5,entities.mentions.PoseUse)。

此前只有 AI Studio 发了 `pose_angle`;画板生成格、工作流「AI 生成素材」节点、智能体 generate_image / generate_video
都没有这一项,而漏斗没有机位就不挂姿势 —— 这三处 `@` 姿势永远发不出去,回执只写一句 `pose_angle_required`。
这里逐个入口钉住「交进漏斗的是用户给的那一份」,外加老数据迁到新名字(`shot_angle`)之后读得出来。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch as mock_patch

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.domain.agent.confirmable import generation as agent_generation
from app.domain.agent.errors import ConfirmationError
from app.domain.entities.mentions import PoseUse
from app.domain.workflows.errors import WorkflowDomainError
from app.domain.workflows.executors import subjobs
from tests.test_entity_generation_paths import _seedance, _workspace
from tests.util import board_revision, fresh_client, run_on_board

FUNNEL = "app.domain.generation.operations.create_generation_job"


class _Stop(Exception):
    """漏斗拿到参数就够了,不往下跑。"""


def _spy(seen: dict):
    def spy(db, **kwargs):
        seen.update(kwargs)
        raise _Stop

    return spy


def test_画板生成格把姿势交进漏斗() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board_id, ws),
        "canvas": {"items": [{"id": "shot", "kind": "image", "x": 0, "y": 0}], "edges": []},
    })
    assert saved.status_code == 200, saved.text
    seen: dict = {}
    with mock_patch(FUNNEL, side_effect=_spy(seen)), pytest.raises(_Stop):
        run_on_board(client, board_id, ws, producer="generate", item_id="shot", kind="image", form={
            "prompt": "她坐在台阶上", "provider": "openai", "model": "gpt-image-1",
            "pose": {"shot_angle": "three_quarter", "as_reference": True},
        })
    assert seen["pose"] == PoseUse(shot_angle="three_quarter", as_reference=True)


def test_画板表单里的机位不对就拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    response = run_on_board(client, board_id, ws, producer="generate", item_id="shot", kind="image", form={
        "prompt": "x", "provider": "openai", "model": "gpt-image-1", "pose": {"shot_angle": "from_above"},
    })
    assert response.status_code == 422


def _confirmation(tool: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(tool=tool, payload=payload, workspace_id="ws", session_id=None)


@pytest.mark.parametrize("tool", ["generate_image", "generate_video"])
def test_智能体的生成卡把姿势交进漏斗(tool: str) -> None:
    seen: dict = {}
    payload = {"prompt": "坐着", "entity_ids": ["e1"], "pose": {"shot_angle": "high_angle"}}
    with mock_patch(FUNNEL, side_effect=_spy(seen)), pytest.raises(_Stop):
        agent_generation._execute_generation(None, _confirmation(tool, payload), "me")
    assert seen["pose"] == PoseUse(shot_angle="high_angle")


def test_智能体的卡上机位不对_开卡就拒() -> None:
    with pytest.raises(ConfirmationError):
        agent_generation._check_pose({"pose": {"shot_angle": "from_above"}})


def test_智能体工具当场说出合法的机位() -> None:
    import mcp_server

    assert mcp_server._pose_payload("side", True) == {"pose": {"shot_angle": "side", "as_reference": True}}
    assert mcp_server._pose_payload("", False) == {}
    with pytest.raises(ValueError, match="three_quarter"):
        mcp_server._pose_payload("from_above", False)


def test_工作流节点把机位和降级开关交进漏斗() -> None:
    fresh_client()
    seen: dict = {}
    scope = SimpleNamespace(workspace_id="ws", id="wf-1")
    config = {"kind": "image", "model": "m", "prompt": "坐着", "entity_ids": "e1",
              "shot_angle": "back", "pose_as_reference": "yes"}
    with SessionLocal() as db, mock_patch(FUNNEL, side_effect=_spy(seen)), \
            mock_patch.object(subjobs, "current_actor", lambda db: None), pytest.raises(_Stop):
        subjobs.ai_generate(db, scope, config)
    assert seen["pose"] == PoseUse(shot_angle="back", as_reference=True)


def test_工作流节点收到不认识的机位_按工作流错误报() -> None:
    with pytest.raises(WorkflowDomainError):
        subjobs._pose_of({"shot_angle": "from_above"})
    assert subjobs._pose_of({}) == PoseUse()


def test_老场景和老生成记录迁到_shot_angle(monkeypatch) -> None:
    from app.db.migrations import _migrate_shot_angle_replaces_camera_angle
    from app.domain import jobs as jobs_bus
    from app.domain.generation.operations import create_generation_job
    from app.domain.generation.origins import STUDIO_ORIGIN

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})
    client = fresh_client()
    ws = _workspace(client)
    scene = client.post("/api/scenes", json={"workspace_id": ws, "name": "S"}).json()
    profile = _seedance(client)
    with SessionLocal() as db:
        generation, _job = create_generation_job(
            db, origin=STUDIO_ORIGIN, workspace_id=ws, session_id=None, project_id=None, created_by=None,
            provider="bytedance", provider_profile_id=profile, model="doubao-seedance-2-0-260128", kind="video",
            prompt="跑", negative_prompt="", parameters={}, source_assets=[],
        )
        db.commit()
        record_id = generation.id
    # 退回 2.4.0 写下的形状:镜头上叫 camera_angle,生成记录里是 pose_angle / pose_mentions_role。
    with engine.begin() as conn:
        content = json.loads(conn.execute(text("SELECT content FROM scenes_3d WHERE id = :id"), {"id": scene["id"]}).scalar())
        content["shots"][0]["camera_angle"] = "high_angle"
        conn.execute(text("UPDATE scenes_3d SET content = :c WHERE id = :id"),
                     {"c": json.dumps(content), "id": scene["id"]})
        conn.execute(text("UPDATE generation_jobs SET request = :r WHERE id = :id"), {"id": record_id, "r": json.dumps({
            "prompt": "跑", "pose_angle": "side", "pose_mentions_role": "reference_image",
            "scene_reference": {"scene_id": scene["id"], "camera_angle": "side"},
        })})

    _migrate_shot_angle_replaces_camera_angle()
    _migrate_shot_angle_replaces_camera_angle()  # 幂等

    shot = client.get(f"/api/scenes/{scene['id']}", params={"workspace_id": ws}).json()["content"]["shots"][0]
    assert shot["shot_angle"] == "high_angle" and "camera_angle" not in shot
    with engine.begin() as conn:
        request = json.loads(conn.execute(text("SELECT request FROM generation_jobs WHERE id = :id"), {"id": record_id}).scalar())
    assert request["pose"] == {"shot_angle": "side", "as_reference": True}
    assert "pose_angle" not in request and "pose_mentions_role" not in request
    assert request["scene_reference"] == {"scene_id": scene["id"], "shot_angle": "side"}
