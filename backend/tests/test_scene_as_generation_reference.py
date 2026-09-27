"""3D 场景当生成的参考(ADR 0029):连进来的是场景,跑的时候现渲。

- 构图参考:这个镜头第 0 秒的白模 → reference_image;首尾帧 → first_frame / last_frame(模型不收尾帧就只给首帧);
- 镜头里看得见的人偶演的人物当 `@` 了它们,提示词写明「这个颜色的人偶是谁」;没出镜的不带;
- 用法要的角色模型不收、图片要首尾帧,当场说;
- 画板:连进生成格的场景格按连线取,和资产格同一条;
- 生成漏斗把渲出来的素材挂上、说明并进提示词、回执记下用的是哪个修订。
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, Entity
from app.domain.scenes import SceneDomainError, scene_reference
from tests.util import board_revision, fresh_client, run_on_board

CAMERA = {"id": "cam-1", "kind": "camera", "position": [0, 1.6, 6], "target": [0, 1.2, 0], "fov": 40,
          "track": [{"time": 0, "position": [0, 1.6, 6], "target": [0, 1.2, 0], "fov": 40},
                    {"time": 5, "position": [0, 1.6, 3], "target": [0, 1.2, 0], "fov": 40}]}


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        people = [Entity(workspace_id=ws, kind="character", name=name, prompt="", attributes={}, tags=[],
                         lost_references=[]) for name in ("小美", "路人")]
        db.add_all(people)
        db.commit()
        mei, passer = people[0].id, people[1].id
    content = {
        "objects": [
            {"id": "ground", "kind": "plane", "parameters": {"width": 20, "depth": 20}},
            {"id": "mei", "name": "小美", "kind": "figure", "position": [0, 0, 0], "color": "#c0504d", "entity_id": mei},
            #: 在相机背后:没出镜,不带它的脸。
            {"id": "passer", "name": "路人", "kind": "figure", "position": [0, 0, 12], "color": "#4d7cc0",
             "entity_id": passer},
            CAMERA,
        ],
        "shots": [{"id": "shot-1", "name": "推近", "duration": 5, "camera_id": "cam-1"}],
    }
    scene = client.post("/api/scenes", json={"workspace_id": ws, "name": "草原", "content": content})
    assert scene.status_code == 200, scene.text
    return client, ws, scene.json()["id"], mei


def test_构图参考_现渲一张_镜头里的人偶带上它演的人物_没出镜的不带() -> None:
    _client, ws, scene_id, mei = _setup()
    with SessionLocal() as db:
        ref = scene_reference(db, ws, scene_id=scene_id, shot_id="", use="composition", kind="image", accepts=lambda role: True)
        [source] = ref.source_assets
        assert source["role"] == "reference_image"
        asset = db.get(Asset, source["asset_id"])
        assert asset.workspace_id == ws and asset.source == "graybox" and asset.kind == "image"
    assert ref.entity_ids == [mei], "只带出镜的那个人"
    assert "草原" in ref.prompt and "#c0504d" in ref.prompt and "「小美」" in ref.prompt and "路人" not in ref.prompt
    assert "运镜" not in ref.prompt, "图片不说运镜"
    assert ref.receipt["revision"] == 1 and ref.receipt["shot_id"] == "shot-1"


def test_首尾帧给视频_模型不收尾帧就只给首帧_并说运镜() -> None:
    _client, ws, scene_id, _mei = _setup()
    with SessionLocal() as db:
        both = scene_reference(db, ws, scene_id=scene_id, shot_id="shot-1", use="frames", kind="video",
                               accepts=lambda role: True)
        only_first = scene_reference(db, ws, scene_id=scene_id, shot_id="shot-1", use="frames", kind="video",
                                     accepts=lambda role: role != "last_frame")
    assert [one["role"] for one in both.source_assets] == ["first_frame", "last_frame"]
    assert [one["role"] for one in only_first.source_assets] == ["first_frame"]
    assert "dolly in" in both.prompt, "运镜描述从机位轨迹算出来"


def test_用法对不上_当场说_不渲() -> None:
    _client, ws, scene_id, _mei = _setup()
    with SessionLocal() as db:
        for use, kind, accepts, key in (
            ("frames", "image", lambda role: True, "sceneErr_referenceUseVideoOnly"),
            ("composition", "image", lambda role: role != "reference_image", "sceneErr_referenceRoleUnsupported"),
            ("motion", "video", lambda role: role != "reference_video", "sceneErr_referenceRoleUnsupported"),
            ("whatever", "image", lambda role: True, "sceneErr_badReferenceUse"),
        ):
            with pytest.raises(SceneDomainError) as refused:
                scene_reference(db, ws, scene_id=scene_id, shot_id="", use=use, kind=kind, accepts=accepts)
            assert refused.value.key == key, use
        assert db.query(Asset).filter(Asset.workspace_id == ws, Asset.source == "graybox").count() == 0


def test_画板上连进生成格的场景按连线取_镜头和用法照表单() -> None:
    client, ws, scene_id, _mei = _setup()
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    canvas = {"items": [{"id": "set", "kind": "scene", "x": 0, "y": 0, "scene_id": scene_id},
                        {"id": "shot", "kind": "video", "x": 400, "y": 0}],
              "edges": [{"id": "set->shot", "source": "set", "target": "shot"}]}
    saved = client.patch(f"/api/boards/{board_id}", json={"workspace_id": ws, "canvas": canvas,
                                                           "base_revision": board_revision(client, board_id, ws)})
    assert saved.status_code == 200, saved.text
    seen: dict = {}

    def spy(db, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("到这儿就够了")

    with mock_patch("app.domain.generation.create_generation_job", side_effect=spy), pytest.raises(RuntimeError):
        run_on_board(client, board_id, ws, producer="generate", item_id="shot", kind="video", x=400, y=0,
                     form={"prompt": "她在跑", "scene_reference": {"shot_id": "shot-1", "use": "frames"}})
    assert seen["scene_reference"] == {"shot_id": "shot-1", "use": "frames", "scene_id": scene_id}


def test_生成漏斗挂上渲出来的素材_说明并进提示词_回执记下修订(monkeypatch) -> None:
    from app.domain import jobs as jobs_bus
    from app.domain.generation import create_generation_job

    from tests.test_entity_generation_paths import _seedance

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})
    client, ws, scene_id, mei = _setup()
    profile = _seedance(client)
    with SessionLocal() as db:
        generation, _job = create_generation_job(
            db, workspace_id=ws, session_id=None, project_id=None, created_by=None, provider="bytedance",
            provider_profile_id=profile, model="doubao-seedance-2-0-260128", kind="video", prompt="她在草原上奔跑",
            negative_prompt="", parameters={}, source_assets=[],
            scene_reference={"scene_id": scene_id, "shot_id": "", "use": "composition"},
        )
        request = generation.request
    assert [one["role"] for one in request["source_assets"]] == ["reference_image"]
    assert request["prompt"].startswith("她在草原上奔跑") and "白模" in request["prompt"]
    assert request["scene_reference"]["scene_id"] == scene_id and request["scene_reference"]["entity_ids"] == [mei]
