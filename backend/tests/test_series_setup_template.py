"""「连续剧 · 系列设定」:集数、角色、场景由用的人定(维护者:「集数、角色、场景应该支持用户自定义」)。

钉住的是:
1. 开始节点里剧名、梗概必填,集数、角色、场景、画风是用户填的格子,提示词把它们原样交给模型、说清「照用户的来」;
2. 角色的嗓子只能从免费的 Edge 中文音色里挑(Schema 写成枚举),存成人物时一起存;
3. 库里已有的人物不重画,但**存成资产每一项都跑** —— 已有的人物也补上嗓子;
4. 用模板真实的角色循环跑一遍:库里有图的不画、只配嗓子,新角色画三视图、存图又存嗓子。
"""

from __future__ import annotations

from typing import Any

from app.core.db import SessionLocal
from app.db.models import Entity, Workflow
from app.domain.workflows.executors import registry as executors_registry
from app.domain.workflows.graph_rules import validate_graph, with_run_params
from app.domain.workflows.templates.model_choice import ModelChoice
from app.domain.workflows.templates.series import SERIES_VOICES, series_setup_graph
from tests.util import fresh_client

CHAT = ModelChoice(profile_id="c", provider="o", model="m")
IMAGE = ModelChoice(profile_id="i", provider="f", model="im")


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(node for node in graph["nodes"] if node["id"] == node_id)


def test_剧名梗概必填_集数角色场景是用户的格子_提示词照用户的来() -> None:
    graph = series_setup_graph(chat=CHAT, image=IMAGE)
    start = _node(graph, "start")["config"]
    assert start["required_params"] == ["title", "premise"]
    assert {"episodes", "characters", "locations", "style"} <= set(start["params"])
    assert start["params"]["episodes"] == 10
    assert validate_graph(graph) != []
    assert validate_graph(with_run_params(graph, {"title": "长明灯", "premise": "灯铺孤女与夜巡使查无面案"})) == []

    bible = _node(graph, "series_bible")["config"]
    for slot in ("{{start.episodes}}", "{{start.characters}}", "{{start.locations}}", "{{start.style}}"):
        assert slot in bible["prompt"]
    assert "集数照用户填的写" in bible["system"] and "一字不差" in bible["system"]
    character = bible["json_schema"]["properties"]["characters"]["items"]["properties"]
    assert character["voice"]["enum"] == [voice.id for voice in SERIES_VOICES]
    assert all(voice.startswith("zh-CN-") for voice in character["voice"]["enum"])


def test_库里已有的人物不重画_但每一项都存一次_补上嗓子() -> None:
    graph = series_setup_graph(chat=CHAT, image=IMAGE)
    body = _node(graph, "character_assets")["config"]["body"]
    control = {(edge["source"], edge["target"]): edge.get("source_handle") for edge in body["edges"] if edge.get("kind") != "data"}
    assert control[("has_art", "sheet")] == "false", "库里有图的不画"
    assert ("find", "save") in control, "存成资产不挂在画图后面:已有的人物也要配上嗓子"
    save = next(node for node in body["nodes"] if node["id"] == "save")
    assert save["config"]["engine"] == "builtin:edge"
    data = {(edge["source"], edge["source_output"], edge["target"], edge["target_input"])
            for edge in body["edges"] if edge.get("kind") == "data"}
    assert ("sheet", "asset_id", "save", "asset_ids") in data


def test_场景循环只取设计稿_存成资产也标设计稿() -> None:
    graph = series_setup_graph(chat=CHAT, image=IMAGE)
    body = _node(graph, "location_assets")["config"]["body"]
    nodes = {one["id"]: one for one in body["nodes"]}
    assert nodes["find"]["config"] == {
        "kind": "location", "name": "{{loop.item.name}}", "limit": 1, "role": "design_sheet",
    }
    assert nodes["save"]["config"]["role"] == "design_sheet"
    assert "2x2 grid of four separate panels" in nodes["art"]["config"]["prompt"]


def test_真跑角色循环_有图的只配嗓子_新角色画三视图并存图存嗓子(monkeypatch) -> None:
    from app.domain.workflows.engine import execute_graph

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    assert client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": "顾长夜"}).status_code == 200
    drawn: list[str] = []

    def fake_generate(db, scope, config):
        drawn.append(config["prompt"].split(":")[0])
        return {"asset_id": "", "asset_ids": []}

    monkeypatch.setitem(executors_registry._REGISTRY, "ai_generate", fake_generate)
    #: 库里的顾长夜「有图」:取资产交出一张参考图(只换这一个出口,找人物、存资产都是真的)。
    real_get = executors_registry.get_executor("entity_get")

    def entity_get_with_art(db, scope, config):
        out = real_get(db, scope, config)
        return {**out, "asset_ids": ["art-1"]} if out["found"] else out

    monkeypatch.setitem(executors_registry._REGISTRY, "entity_get", entity_get_with_art)
    graph = series_setup_graph(chat=CHAT, image=IMAGE)
    loop = _node(graph, "character_assets")
    bible = {"json": {"style_prompt": "ink", "title": "长明灯", "characters": [
        {"name": "顾长夜", "role": "夜巡使", "appearance": "tall young man", "voice": "zh-CN-YunxiNeural"},
        {"name": "沈青禾", "role": "灯铺孤女", "appearance": "girl with a braid", "voice": "zh-CN-XiaoyiNeural"},
    ]}}
    monkeypatch.setitem(executors_registry._REGISTRY, "code", lambda db, scope, config: bible)
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="t", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    nodes = [{"id": "series_bible", "type": "code", "config": {}}, loop]
    edges = [edge for edge in graph["edges"] if edge["target"] == "character_assets" and edge["source"] == "series_bible"]
    context, cancelled = execute_graph({"nodes": nodes, "edges": edges}, wf_id=wf_id, entry_is_root=True)
    assert not cancelled
    assert drawn == ["Character turnaround reference sheet for 沈青禾"], "库里有图的顾长夜不重画"
    with SessionLocal() as db:
        voices = {entity.name: (entity.attributes or {}).get("voice", {}).get("voice")
                  for entity in db.query(Entity).filter(Entity.workspace_id == ws)}
    assert voices == {"顾长夜": "zh-CN-YunxiNeural", "沈青禾": "zh-CN-XiaoyiNeural"}
