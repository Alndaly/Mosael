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
