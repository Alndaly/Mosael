"""「运行工作流」卡上点名的是**真要跑的那一张**,名字由开卡时查出来,不由调用方转述。

MCP 的 run_workflow 只带 workflow_id(mcp_server.run_workflow),而摘要读 `payload["name"]`、读不到就退回 id ——
卡标题于是是一串 uuid:用户在授权界面上认不出自己要批的是哪一张。反过来,调用方自带的 name 也不能信。
"""

from __future__ import annotations

import mcp_server
from tests.util import fresh_client, user_id


def _workflow(client, ws: str, name: str) -> str:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": name, "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
                  {"id": "t", "type": "template", "config": {"template": "x"}}],
        "edges": [{"id": "e", "source": "start", "target": "t"}]}}).json()["id"]


def test_MCP_开的运行卡_标题是工作流的名字不是_id() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = _workflow(client, ws, "日更短视频")

    with mcp_server.calling_as(user_id=user_id(), requested_by="mcp"):
        card = mcp_server.run_workflow(workflow_id=wf, workspace_id=ws)

    shown = client.get(f"/api/confirmations/{card['confirmation_id']}").json()
    assert "「日更短视频」" in shown["headline"], shown["headline"]
    assert wf not in shown["headline"]


def test_调用方自带的名字不算数() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = _workflow(client, ws, "群发通知")

    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi",
        "payload": {"workflow_id": wf, "name": "无害的小测试", "params": {}},
    }).json()

    assert "「群发通知」" in card["headline"] and "无害的小测试" not in card["headline"]
