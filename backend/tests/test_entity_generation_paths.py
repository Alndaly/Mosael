"""`@资产` 从各个入口走到生成漏斗(ADR 0027 阶段 2),以及画板上的资产格。

- AI 工作台(`POST /api/generation/jobs` 带 `entity_ids`):请求里记下拼好的提示词、挂上的参考图和回执;
- 画板:资产格连进生成格 = `@` 了它,和正文里 `@` 的走同一个参数(`entity_ids`);
- 资产格存得下、引用别处的资产存不下、资产删了那一格照样存得下;
- 分享到社区的快照里,资产格像一张图片格那样带封面和名字,不带本机 id。
"""

from __future__ import annotations

from unittest.mock import patch as mock_patch

import pytest

from app.core.db import SessionLocal
from app.db.models import Entity, EntityReference, ProviderProfile
from app.domain import provider_models
from app.domain.generation.operations import prompt_for_provider
from tests.util import board_revision, fresh_client, run_on_board, seed_assets


@pytest.fixture(autouse=True)
def _generation_jobs_不外发(monkeypatch: pytest.MonkeyPatch):
    """只关心「建成什么样」,不真跑:标成 external,任务照常建好、线程不起(同 test_generation_declaration_paths)。"""
    from app.domain import jobs as jobs_bus

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _entity(ws: str, name: str, prompt: str, refs: list[tuple[str, str]]) -> str:
    with SessionLocal() as db:
        entity = Entity(workspace_id=ws, kind="character", name=name, prompt=prompt, attributes={}, tags=[],
                        lost_references=[])
        db.add(entity)
        db.flush()
        for position, (asset_id, role) in enumerate(refs, start=1):
            db.add(EntityReference(entity_id=entity.id, asset_id=asset_id, role=role, position=position))
        db.commit()
        return entity.id


def _seedance(client) -> str:
    """一条火山的连接,挂 Seedance 2(catalog 里的真描述符:参考图最多 9 张,首尾帧与参考素材互斥)。"""
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "bytedance", "name": "火山", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, profile_id), "doubao-seedance-2-0-260128",
                               source="manual", capability_ids=["video"])
        db.commit()
    return profile_id


def test_AI_工作台_点名资产_请求里记下拼好的提示词和挂上的参考图() -> None:
    client = fresh_client()
    ws = _workspace(client)
    seed_assets(ws, {"front": "image", "sheet": "image", "first": "image"})
    zhang = _entity(ws, "张三", "黑色短发,红围巾", [("front", "front"), ("sheet", "turnaround")])
    profile = _seedance(client)

    res = client.post("/api/generation/jobs", json={
        "workspace_id": ws, "provider_profile_id": profile, "provider": "bytedance",
        "model": "doubao-seedance-2-0-260128", "kind": "video", "prompt": "张三走过老街",
        "entity_ids": [zhang],
    })
    assert res.status_code == 200, res.text
    request = res.json()["generation"]["request"]
    # 记录上是他写的那句;描述是补给模型的一段,交给供应商时才接上(生成记录的用户气泡只画他说的话)。
    assert request["prompt"] == "张三走过老街"
    assert request["prompt_notes"] == ["张三: 黑色短发,红围巾"]
    assert prompt_for_provider(request) == "张三走过老街\n\n张三: 黑色短发,红围巾"
    assert request["source_assets"] == [
        {"asset_id": "sheet", "role": "reference_image"}, {"asset_id": "front", "role": "reference_image"},
    ]
    assert request["entities"][0]["attached"] == ["sheet", "front"]
    assert request["entities"][0]["dropped"] == []

    # 已经挂了首帧:和参考图互斥,一张不挂,回执里说为什么。
    blocked = client.post("/api/generation/jobs", json={
        "workspace_id": ws, "provider_profile_id": profile, "provider": "bytedance",
        "model": "doubao-seedance-2-0-260128", "kind": "video", "prompt": "张三走过老街",
        "source_assets": [{"asset_id": "first", "role": "first_frame"}], "entity_ids": [zhang],
    }).json()["generation"]["request"]
    assert blocked["source_assets"] == [{"asset_id": "first", "role": "first_frame"}]
    assert blocked["entities"][0]["notes"] == ["exclusive"]
    assert blocked["entities"][0]["dropped"] == ["sheet", "front"]


def test_点名别的工作区的资产_提交当场拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    other = _workspace(client)
    stranger = _entity(other, "外人", "", [])
    profile = _seedance(client)
    res = client.post("/api/generation/jobs", json={
        "workspace_id": ws, "provider_profile_id": profile, "provider": "bytedance",
        "model": "doubao-seedance-2-0-260128", "kind": "video", "prompt": "街景", "entity_ids": [stranger],
    })
    assert res.status_code == 422


def _board_with_entity_cell(client, ws: str, entity_id: str) -> str:
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    canvas = {
        "items": [
            {"id": "who", "kind": "entity", "x": 0, "y": 0, "entity_id": entity_id},
            {"id": "shot", "kind": "image", "x": 300, "y": 0},
        ],
        "edges": [{"id": "who->shot", "source": "who", "target": "shot"}],
    }
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "canvas": canvas, "base_revision": board_revision(client, board_id, ws),
    })
    assert saved.status_code == 200, saved.text
    return board_id


def test_资产格存得下_别处的资产存不下_删了照样存得下() -> None:
    client = fresh_client()
    ws = _workspace(client)
    zhang = _entity(ws, "张三", "", [])
    board_id = _board_with_entity_cell(client, ws, zhang)
    items = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()["canvas"]["items"]
    assert items[0] == {"id": "who", "kind": "entity", "x": 0.0, "y": 0.0, "entity_id": zhang}

    other = _workspace(client)
    stranger = _entity(other, "外人", "", [])
    bad = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board_id, ws),
        "canvas": {"items": [{"id": "x", "kind": "entity", "x": 0, "y": 0, "entity_id": stranger}], "edges": []},
    })
    assert bad.status_code == 400
    missing = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "base_revision": board_revision(client, board_id, ws),
        "canvas": {"items": [{"id": "x", "kind": "entity", "x": 0, "y": 0}], "edges": []},
    })
    assert missing.status_code == 400

    # 资产删了:已经在板上的那一格照样能挪、能存。
    client.delete(f"/api/entities/{zhang}")
    board = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()
    moved = board["canvas"]
    moved["items"][0]["x"] = 50
    again = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "canvas": moved, "base_revision": board["revision"],
    })
    assert again.status_code == 200, again.text


def _spy_generation(client, ws: str, board_id: str, form: dict) -> dict:
    seen: dict = {}

    def spy(db, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("到这儿就够了")

    with mock_patch("app.domain.generation.create_generation_job", side_effect=spy):
        with pytest.raises(RuntimeError):
            run_on_board(client, board_id, ws, producer="generate", item_id="shot", kind="image", x=300, y=0,
                         form={"prompt": "站在街口", "provider": "openai", "model": "gpt-image-1", **form})
    return seen


def test_资产格连进生成格_和_at_走同一个参数() -> None:
    client = fresh_client()
    ws = _workspace(client)
    zhang = _entity(ws, "张三", "黑色短发", [])
    li = _entity(ws, "李四", "", [])
    board_id = _board_with_entity_cell(client, ws, zhang)

    upstream_only = _spy_generation(client, ws, board_id, {})
    assert upstream_only["entity_ids"] == [zhang], "连进来的资产格等于 @ 了它"

    both = _spy_generation(client, ws, board_id, {"entity_ids": [li, zhang]})
    assert both["entity_ids"] == [li, zhang], "正文里 @ 的在前,连进来的并进去,不重复"


def test_正文里_at_的资产存在格子的表单上() -> None:
    client = fresh_client()
    ws = _workspace(client)
    zhang = _entity(ws, "张三", "", [])
    board_id = client.post("/api/boards", json={"workspace_id": ws}).json()["id"]
    canvas = {"items": [{"id": "shot", "kind": "image", "x": 0, "y": 0,
                         "form": {"prompt": "张三", "mentioned_entity_ids": [zhang, zhang, " "]}}], "edges": []}
    saved = client.patch(f"/api/boards/{board_id}", json={
        "workspace_id": ws, "canvas": canvas, "base_revision": board_revision(client, board_id, ws),
    }).json()
    assert saved["canvas"]["items"][0]["form"]["mentioned_entity_ids"] == [zhang]
    usage = client.get(f"/api/entities/{zhang}/usage").json()
    assert [(row["id"], row["how"]) for row in usage["boards"]] == [(board_id, "mention")]


def test_工作流生成节点的_entity_ids_交给同一个漏斗() -> None:
    """节点的 `entity_ids` 可以是挑出来的一串,也可以是上游插值出来的一段字(逗号 / 换行分隔)。"""
    from types import SimpleNamespace

    from app.domain.workflows.executors import get_executor

    seen: dict = {}

    def spy(db, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("到这儿就够了")

    fresh_client()
    scope = SimpleNamespace(workspace_id="ws-1", id="wf-1", name="流程")
    with SessionLocal() as db, mock_patch("app.domain.generation.create_generation_job", side_effect=spy):
        with pytest.raises(RuntimeError):
            get_executor("ai_generate")(db, scope, {"kind": "image", "prompt": "街口", "entity_ids": "e1, e2\ne1"})
    assert seen["entity_ids"] == ["e1", "e2"]
    assert seen["workspace_id"] == "ws-1"
