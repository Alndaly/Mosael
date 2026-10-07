"""确认卡记下**是哪一次工具调用开的它**,对话里才能把卡摆回那次调用的位置。

用户截图:同一轮里智能体连着请求了五条「生成音频」,五张卡全批了、全「✓ 已执行」,却一张接一张堆在
输入框上面,把那一轮正在跑的工具行顶上去。卡只知道自己属于哪次对话(session_id),不知道属于对话里的
哪一步 —— 界面无从把它放回去,只能统一堆在末尾。

这个 id 只管**摆在哪儿**,不管授权:它由运行时(sidecar)随调用报上来,报错了也只是卡摆错了地方,
归属(哪次对话、能不能自动放行)照旧由凭据决定。
"""

from __future__ import annotations

import sqlalchemy as sa

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import ToolConfirmation, User
from app.domain.agent.autopilot import wait_for_idle_autopilot
from tests.test_plugin_tool_confirmation import Setup, _card
from tests.util import fresh_client

WORKFLOW = {
    "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
              {"id": "t", "type": "template", "config": {"template": "x"}}],
    "edges": [{"id": "e", "source": "start", "target": "t"}],
}


def _turn(client) -> tuple[str, str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws, "title": "T"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, me.id, agent_session_id=sid)
    return ws, sid, token


def test_内置工具开的卡记下那次调用_列表和单张都带出来() -> None:
    client = fresh_client()
    ws, sid, token = _turn(client)
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": WORKFLOW}).json()["id"]

    response = client.post(
        "/api/agent/tools/run_workflow",
        json={"arguments": {"workflow_id": wf, "workspace_id": ws}, "requested_by": "pi", "tool_call_id": "call-7"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    card_id = response.json()["result"]["confirmation_id"]
    wait_for_idle_autopilot(timeout=10)

    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card_id).tool_call_id == "call-7"
    listed = client.get("/api/confirmations", params={"workspace_id": ws, "session_id": sid}).json()
    assert [(one["id"], one["tool_call_id"]) for one in listed] == [(card_id, "call-7")]
    assert client.get(f"/api/confirmations/{card_id}").json()["tool_call_id"] == "call-7"


def test_插件工具开的卡也记下那次调用() -> None:
    setup = Setup()
    setup.as_turn()
    response = setup.client.post(
        f"/api/agent/tools/{setup.name('render')}",
        json={"arguments": {"code": "print(1)"}, "tool_call_id": "call-plugin"},
    )
    assert response.status_code == 200, response.text
    card = _card(response.json()["result"]["confirmation_id"])
    assert card.tool_call_id == "call-plugin"


def test_不是工具调用开的卡_没有这一项() -> None:
    """MCP 直连、POST /api/confirmations 开的卡没有「对话里的哪一步」—— 留空,由全局确认中心兜底。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": WORKFLOW}).json()["id"]
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "run_workflow", "requested_by": "mcp", "payload": {"workflow_id": wf, "params": {}},
    }).json()
    assert card["tool_call_id"] is None


def test_迁移给老库的确认卡表补上这一列_老卡留空_重跑不动() -> None:
    from app.core.db import engine
    from app.db import migrations

    fresh_client()
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE tool_confirmations"))
        conn.execute(sa.text(
            "CREATE TABLE tool_confirmations (id VARCHAR(64) PRIMARY KEY, workspace_id VARCHAR(64) NOT NULL, "
            "session_id VARCHAR(64), tool VARCHAR(80) NOT NULL, permission VARCHAR(40) NOT NULL, "
            "summary VARCHAR(500) NOT NULL DEFAULT '', status VARCHAR(24) NOT NULL DEFAULT 'pending')"
        ))
        conn.execute(sa.text(
            "INSERT INTO tool_confirmations (id, workspace_id, session_id, tool, permission, status) "
            "VALUES ('old', 'w', 's', 'run_workflow', 'ai-cost', 'executed')"
        ))

    migrations._migrate_tool_confirmations_name_their_tool_call()
    migrations._migrate_tool_confirmations_name_their_tool_call()

    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(tool_confirmations)"))}
        assert "tool_call_id" in columns
        assert conn.execute(sa.text("SELECT tool_call_id FROM tool_confirmations WHERE id='old'")).scalar() is None
    fresh_client()
