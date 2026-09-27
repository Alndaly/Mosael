"""智能体的资产工具(ADR 0027):list_entities / get_entity / create_entity / attach_entity_reference,
以及 generate_image 带 `entity_ids` 时,批准之后的结果里说得出挂了哪几张参考图。

工具经 mcp_server 的 HTTP 出口打到后端(和 test_mcp_tool_payloads 同一种接法),判的是后端真落下的东西。
"""

from __future__ import annotations

import mcp_server
from tests.test_mcp_tool_payloads import _route_through
from tests.util import fresh_client, seed_assets


def test_建人物_挂参考图_读回来_列出来(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"face": "image", "sheet": "image"})
    _route_through(monkeypatch, client)

    made = mcp_server.create_entity(kind="character", name="张三", prompt="黑色短发,红围巾", tags=["主角"], workspace_id=ws)
    assert made["name"] == "张三" and made["prompt"] == "黑色短发,红围巾"
    variant = mcp_server.create_entity(kind="character", name="冬装", prompt="羽绒服", parent_id=made["id"], workspace_id=ws)
    assert variant["parent_name"] == "张三"

    mcp_server.attach_entity_reference(made["id"], "face", role="front", cover=True)
    got = mcp_server.attach_entity_reference(made["id"], "sheet", role="turnaround")
    assert [(r["asset_id"], r["role"]) for r in got["references"]] == [("face", "front"), ("sheet", "turnaround")]
    assert got["cover_asset_id"] == "face"

    detail = mcp_server.get_entity(made["id"])
    assert [v["name"] for v in detail["variants"]] == ["冬装"]
    listed = mcp_server.list_entities(kind="character", workspace_id=ws)
    assert [(row["name"], row["reference_count"], row["variant_count"]) for row in listed] == [("张三", 2, 1)]
    assert mcp_server.list_entities(query="红围巾", workspace_id=ws)[0]["id"] == made["id"]
    assert mcp_server.list_entities(kind="prop", workspace_id=ws) == []


def test_生成带上_entity_ids_批准之后结果里有回执(monkeypatch) -> None:
    monkeypatch.setattr("app.domain.generation.runner.start_generation_thread", lambda _generation_id: None)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    seed_assets(ws, {"face": "image"})
    entity = client.post("/api/entities", json={"workspace_id": ws, "kind": "character", "name": "张三",
                                                "prompt": "黑色短发"}).json()
    client.post(f"/api/entities/{entity['id']}/references", json={"asset_id": "face", "role": "front"})
    profile = client.post("/api/settings/providers", json={"name": "百炼", "vendor": "alibaba", "config": {"api_key": "k"}}).json()
    client.post(f"/api/settings/providers/{profile['id']}/models",
                json={"model_id": "qwen-image", "enabled": True, "capability_ids": ["image"]})
    _route_through(monkeypatch, client)

    reply = mcp_server.generate_image(prompt="张三在雨里", provider="alibaba", model="qwen-image",
                                      entity_ids=[entity["id"]], workspace_id=ws)
    confirmation_id = reply["confirmation_id"]
    card = client.get(f"/api/confirmations/{confirmation_id}").json()
    assert card["payload"]["entity_ids"] == [entity["id"]]
    approved = client.post(f"/api/confirmations/{confirmation_id}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    receipt = approved["result"]["entities"][0]
    assert receipt["name"] == "张三"
    # qwen-image 是文生图:描述符里没有参考图这个角色 —— 一张不挂,并且说得出为什么。
    assert receipt["attached"] == [] and receipt["notes"] == ["no_reference_role"]
    job = client.get(f"/api/jobs/{approved['result']['job_id']}").json()
    assert job["payload"]["request"]["prompt"].endswith("张三: 黑色短发")
