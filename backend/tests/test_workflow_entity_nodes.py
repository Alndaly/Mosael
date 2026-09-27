"""工作流里的资产库节点(ADR 0027 阶段 4):「取资产」「存成资产」,以及按种类筛的资产下拉。"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.core.db import SessionLocal
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors.entities import entity_get, entity_save
from app.domain.workflows.field_options import OptionContext, field_options
from tests.util import fresh_client, seed_assets


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"front": "image", "sheet": "image", "side": "image", "winter": "image", "clip": "video"})
    return client, ws


def _character(client, ws: str, name: str = "林小满", **body):
    made = client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": name, **body})
    assert made.status_code == 200, made.text
    return made.json()


def _scope(ws: str):
    return SimpleNamespace(workspace_id=ws, id="wf", name="测试流程")


def test_取资产_点名一个_交出提示词描述和按挑图先后排的参考图() -> None:
    client, ws = _setup()
    made = _character(client, ws, prompt="短发,校服", attributes={"voice_engine": "edge", "voice_id": "zh-CN-XiaoxiaoNeural"})
    for asset_id, role in (("side", "side"), ("front", "front"), ("sheet", "turnaround"), ("clip", "concept")):
        client.post(f"/api/entities/{made['id']}/references", json={"asset_id": asset_id, "role": role})
    with SessionLocal() as db:
        out = entity_get(db, _scope(ws), {"entity_id": made["id"]})
    assert out["found"] == 1 and out["name"] == "林小满" and out["prompt"] == "短发,校服"
    assert out["asset_ids"] == ["sheet", "front", "side"], "三视图 > 正面 > 其余;视频不交"
    assert out["asset_id"] == "sheet", "没设封面时是挑图顺序的第一张"
    assert (out["voice_engine"], out["voice_id"]) == ("edge", "zh-CN-XiaoxiaoNeural")

    variant = client.post(f"/api/entities/{made['id']}/variants", json={"name": "冬装", "prompt": "羽绒服"}).json()
    client.post(f"/api/entities/{variant['id']}/references", json={"asset_id": "winter"})
    with SessionLocal() as db:
        out = entity_get(db, _scope(ws), {"entity_id": variant["id"], "limit": 1})
    assert out["name"] == "林小满 · 冬装" and out["prompt"] == "短发,校服，羽绒服", "变体带着母体的描述"
    assert out["asset_ids"] == ["winter"]


def test_取资产_按名字找_找不到给_0_不报错_点名的找不到才报错() -> None:
    client, ws = _setup()
    made = _character(client, ws)
    with SessionLocal() as db:
        hit = entity_get(db, _scope(ws), {"kind": "character", "name": "  林小满 "})
        miss = entity_get(db, _scope(ws), {"kind": "character", "name": "阿澄"})
        wrong_kind = entity_get(db, _scope(ws), {"kind": "prop", "name": "林小满"})
        assert hit["entity_id"] == made["id"] and hit["found"] == 1
        assert miss["found"] == 0 and miss["entity_id"] == "" and miss["asset_ids"] == []
        assert wrong_kind["found"] == 0
        with pytest.raises(WorkflowDomainError):
            entity_get(db, _scope(ws), {})
        with pytest.raises(WorkflowDomainError):
            entity_get(db, _scope(ws), {"entity_id": "no-such"})


def test_存成资产_新建_再存同名的是合并_不覆盖人手改过的() -> None:
    client, ws = _setup()
    with SessionLocal() as db:
        first = entity_save(db, _scope(ws), {
            "kind": "character", "name": "阿澄", "prompt": "高个子男生", "asset_ids": ["front", "sheet"],
            "role": "turnaround", "tags": "配角",
        })
    assert first["created"] == 1 and first["added"] == 2
    entity = client.get(f"/api/entities/{first['entity_id']}").json()
    assert [(r["asset_id"], r["role"]) for r in entity["references"]] == [("front", "turnaround"), ("sheet", "turnaround")]
    assert entity["prompt"] == "高个子男生" and entity["tags"] == ["配角"]

    client.patch(f"/api/entities/{first['entity_id']}", json={"prompt": "人手改过的描述"})
    with SessionLocal() as db:
        again = entity_save(db, _scope(ws), {
            "kind": "character", "name": "阿澄", "prompt": "另一段描述", "description": "补上的描述",
            "asset_ids": "sheet, side",
        })
    assert again == {"entity_id": first["entity_id"], "created": 0, "added": 1, "name": "阿澄"}
    entity = client.get(f"/api/entities/{first['entity_id']}").json()
    assert entity["prompt"] == "人手改过的描述", "合并不覆盖已经写好的"
    assert entity["description"] == "补上的描述", "空着的才填"
    assert [r["asset_id"] for r in entity["references"]] == ["front", "sheet", "side"]

    with SessionLocal() as db:
        other = entity_save(db, _scope(ws), {"kind": "character", "name": "阿澄", "if_exists": "new"})
        assert other["created"] == 1 and other["entity_id"] != first["entity_id"]
        with pytest.raises(WorkflowDomainError):
            entity_save(db, _scope(ws), {"kind": "character", "name": " "})
        with pytest.raises(WorkflowDomainError):
            entity_save(db, _scope(ws), {"kind": "robot", "name": "x"})


def test_在工作流里跑_存下来再按上游的_id_取() -> None:
    client, ws = _setup()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "save", "type": "entity_save", "config": {"kind": "location", "name": "旧城天台", "asset_ids": "front"}},
            {"id": "get", "type": "entity_get", "config": {"entity_id": "{{save.entity_id}}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "save"}, {"id": "e2", "source": "save", "target": "get"}],
    }
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "存资产", "graph": graph})
    assert wf.status_code == 200, wf.text
    job_id = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"params": {}}).json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job
    context = job["result"]["context"]
    assert context["get"]["name"] == "旧城天台" and context["get"]["asset_ids"] == ["front"]
    listed = client.get("/api/entities", params={"workspace_id": ws, "kind": "location"}).json()
    assert [one["name"] for one in listed] == ["旧城天台"]


def test_资产下拉可以按种类筛() -> None:
    client, ws = _setup()
    _character(client, ws)
    client.post("/api/entities", json={"workspace_id": ws, "kind": "prop", "name": "红伞"})
    ctx = OptionContext(workspace_id=ws, user_id=None, parent="", locale="zh")
    with SessionLocal() as db:
        every = [one["label"] for one in field_options(db, "entities", ctx)]
        props = [one["label"] for one in field_options(db, "entities.prop", ctx)]
        roles = {one["value"]: one["label"] for one in field_options(db, "entity_roles", ctx)}
    assert len(every) == 2 and props == ["道具 · 红伞"]
    assert roles["front"] == "正面" and roles["turnaround"] == "三视图"


def test_整片模板的角色循环_库里有的直接用_没有的画完存成资产(monkeypatch) -> None:
    """「从主题到完整视频」的角色循环体原样拿来跑:林小满库里有图,阿澄没有 —— 只画阿澄,画完存成人物资产。"""
    from app.domain.workflows import executors
    from app.domain.workflows.templates import full_video_generation_graph
    from tests.test_workflow_templates import CHAT, SEEDANCE, SEEDREAM

    client, ws = _setup()
    known = _character(client, ws)
    client.post(f"/api/entities/{known['id']}/references", json={"asset_id": "front", "role": "front"})
    drawn: list[str] = []

    def fake_generate(db, scope, config):
        drawn.append(config["prompt"])
        return {"asset_id": "sheet", "asset_ids": ["sheet"], "generation_id": "g"}

    monkeypatch.setitem(executors._REGISTRY, "ai_generate", fake_generate)
    template = full_video_generation_graph(chat=CHAT, image=SEEDREAM, video=SEEDANCE)
    loop = next(node for node in template["nodes"] if node["id"] == "character_sheets")
    characters = [{"name": "林小满", "appearance": "short hair", "role": "主角"},
                  {"name": "阿澄", "appearance": "tall boy", "role": "同学"}]
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {**loop, "config": {**loop["config"], "items": characters, "inputs": {"style": "anime"}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "character_sheets"}],
    }
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "认角色", "graph": graph})
    assert wf.status_code == 200, wf.text
    job_id = client.post(f"/api/workflows/{wf.json()['id']}/run", json={"params": {}}).json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "succeeded", job
    assert len(drawn) == 1 and "阿澄" in drawn[0], "库里有图的林小满不再重画"
    assert job["result"]["context"]["character_sheets"]["results"] == ["front:reference_image", "sheet:reference_image"]
    saved = [one for one in client.get("/api/entities", params={"workspace_id": ws, "kind": "character"}).json()
             if one["name"] == "阿澄"]
    assert len(saved) == 1
    entity = client.get(f"/api/entities/{saved[0]['id']}").json()
    assert entity["prompt"] == "tall boy" and [(r["asset_id"], r["role"]) for r in entity["references"]] == [("sheet", "turnaround")]


def test_列资产_按种类列_交出给模型读的清单() -> None:
    from app.domain.workflows.executors.entities import entity_list

    client, ws = _setup()
    _character(client, ws, prompt="短发,校服")
    _character(client, ws, name="阿澄")
    client.post("/api/entities", json={"workspace_id": ws, "kind": "location", "name": "旧城天台", "prompt": "rooftop"})
    with SessionLocal() as db:
        people = entity_list(db, _scope(ws), {"kind": "character"})
        places = entity_list(db, _scope(ws), {"kind": "location"})
        empty = entity_list(db, _scope(ws), {"kind": "prop"})
    assert people["count"] == 2 and {one["name"] for one in people["entities"]} == {"林小满", "阿澄"}
    assert "- 林小满 — 短发,校服" in people["text"] and "- 阿澄 — (无描述)" in people["text"]
    assert places["text"] == "- 旧城天台 — rooftop"
    assert empty == {"entities": [], "count": 0, "text": ""}
