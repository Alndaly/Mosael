"""「任意长度的连续视频」模板:按模型能力选接法,图合法,真跑起来每段接着上一段(ADR 0092)。"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.jobs import wait_for_idle_jobs
from app.domain.workflows.executors import registry
from app.domain.workflows.graph_rules import validate_graph
from app.domain.workflows.templates_long_take import long_take_video_graph
from app.domain.workflows.templates_models import ModelChoice
from tests.util import fresh_client

CHAT = ModelChoice("c", "anthropic", "claude")
WAN_T2V = ModelChoice("a", "alibaba", "wan2.7-t2v")
WAN_I2V = ModelChoice("a", "alibaba", "wan2.7-i2v")
SEEDANCE = ModelChoice("b", "bytedance", "doubao-seedance-2-0-260128")


def _node(graph: dict, node_id: str) -> dict:
    return next(node for node in graph["nodes"] if node["id"] == node_id)


def _body(graph: dict, loop: str, node_id: str) -> dict:
    return next(node for node in _node(graph, loop)["config"]["body"]["nodes"] if node["id"] == node_id)


def test_收待续写片段的模型_交尾巴_上时间线去掉重叠() -> None:
    graph = long_take_video_graph(chat=CHAT, opening=WAN_T2V, video=WAN_I2V)
    assert _body(graph, "segments", "tail")["type"] == "media_clip"
    assert _body(graph, "segments", "extend")["config"]["source_assets"] == ["{{tail.asset_id}}:first_clip"]
    wired = _node(graph, "assemble")["config"]["body"]["edges"]
    assert any(edge.get("source") == "seam" and edge.get("target_input") == "start" for edge in wired), "时间线要从找到的接缝接"


def test_只收首帧的模型_交最后一帧_不用去掉什么() -> None:
    graph = long_take_video_graph(chat=CHAT, opening=SEEDANCE, video=SEEDANCE)
    assert _body(graph, "segments", "tail")["type"] == "video_frame"
    assert _body(graph, "segments", "extend")["config"]["source_assets"] == ["{{tail.asset_id}}:first_frame"]
    assert _body(graph, "assemble", "append_segment")["config"]["start"] == 0


def test_图是合法的_循环只能一段一段跑() -> None:
    graph = long_take_video_graph(chat=CHAT, opening=WAN_T2V, video=WAN_I2V)
    assert validate_graph({**graph, "nodes": [
        {**node, "config": {**node["config"], "params": {**node["config"]["params"], "idea": "x"}, "required_params": []}} if node["id"] == "start" else node
        for node in graph["nodes"]
    ]}) == []
    assert _node(graph, "segments")["config"].get("concurrency", 1) == 1


@pytest.fixture
def fake_run(monkeypatch):
    """生成、截取、时间线都换成记账的假执行器:只看每一段接的是不是上一段。"""
    seen: dict[str, list[Any]] = {"generated": [], "tails": [], "appended": [], "seams": []}

    def llm(db, scope, config):
        return {"text": "", "json": {"opening": "开场", "next": ["甲", "乙"]}}

    def generate(db, scope, config):
        seen["generated"].append({"prompt": config["prompt"].strip(), "sources": config.get("source_assets")})
        return {"asset_id": f"seg{len(seen['generated'])}", "asset_ids": [], "generation_id": "g"}

    def clip(db, scope, config):
        seen["tails"].append(config["asset_id"])
        return {"asset_id": f"tail-of-{config['asset_id']}", "source_asset_id": config["asset_id"], "start": 0, "end": 1, "duration": 1}

    def append(db, scope, config):
        seen["appended"].append((config["asset_id"], config.get("start")))
        return {"clip_id": "c", "timeline_start": 0, "timeline_end": 1, "duration": 1, "trimmed": 0, "sequence_id": config["sequence_id"]}

    for node_type, handler in {
        "llm": llm, "ai_generate": generate, "media_clip": clip, "timeline_append": append,
        "project_sequence_create": lambda db, scope, config: {"project_id": "p", "sequence_id": "s", "video_track_id": "v", "audio_track_id": "a", "name": "n"},
        "timeline_clear": lambda db, scope, config: {"removed": 0, "sequence_id": "s"},
        "export_sequence": lambda db, scope, config: {"asset_id": "final"},
        "video_seam": lambda db, scope, config: seen["seams"].append((config["previous_asset_id"], config["asset_id"])) or {"start": 1.5},
        "video_cost_estimate": lambda db, scope, config: {"count": 3, "seconds": 15, "estimate": None, "currency": "", "text": ""},
    }.items():
        monkeypatch.setitem(registry._REGISTRY, node_type, handler)
    return seen


def test_真跑一遍_每段接着上一段的尾巴(fake_run) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Workflow
    from app.domain.workflows.engine import execute_graph

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="长片", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    graph = long_take_video_graph(chat=CHAT, opening=WAN_T2V, video=WAN_I2V)
    context, _ = execute_graph(graph, wf_id=wf_id, params={"idea": "走路"})
    wait_for_idle_jobs()
    assert fake_run["tails"] == ["seg1", "seg2"]
    assert ["tail-of-seg1" in str(fake_run["generated"][1]["sources"]), "tail-of-seg2" in str(fake_run["generated"][2]["sources"])] == [True, True]
    assert [asset for asset, _ in fake_run["appended"]] == ["seg1", "seg2", "seg3"]
    assert [start for _, start in fake_run["appended"]][1:] == [1.5, 1.5]
    assert fake_run["seams"] == [("seg1", "seg2"), ("seg2", "seg3")], "接缝要拿前一段和这一段比"
    assert context["export_final"]["asset_id"] == "final"


def _estimate(monkeypatch, cost_micros: int | None, **config: Any) -> dict:
    from types import SimpleNamespace

    from app.domain.billing.usage import Pricing
    from app.domain.workflows.executors import subjobs

    seen: dict[str, Any] = {}

    def price(db, **kwargs):
        seen.update(kwargs)
        return Pricing(cost_micros=cost_micros, currency="CNY" if cost_micros is not None else None)

    monkeypatch.setattr(subjobs, "price_usage", price)
    made = subjobs.video_cost_estimate(None, SimpleNamespace(workspace_id="w"), {
        "provider": "alibaba", "model": "wan2.7-i2v", "items": ["甲", "乙"], "extra_items": 1, "seconds_each": 5, **config,
    })
    assert seen["units"]["video_seconds"] == 15
    return made


def test_估算_段数乘秒数按价目算(monkeypatch) -> None:
    made = _estimate(monkeypatch, 12_000_000, max_spend=20)
    assert (made["count"], made["seconds"], made["estimate"], made["currency"]) == (3, 15, 12.0, "CNY")


def test_估算超了上限_在花钱之前停(monkeypatch) -> None:
    from app.domain.workflows.errors import WorkflowDomainError

    with pytest.raises(WorkflowDomainError) as caught:
        _estimate(monkeypatch, 12_000_000, max_spend=10)
    assert caught.value.key == "wfErr_estimateOverBudget"


def test_没配价目的模型_估不出就照常往下走(monkeypatch) -> None:
    made = _estimate(monkeypatch, None, max_spend=10)
    assert made["estimate"] is None and made["text"]
