"""「本会话始终允许」记的是 (工具, 当时那一档),只放行不高于那一档的卡。

此前白名单只记工具名(`confirmation.tool in session.auto_allow_tools`),而同一个工具的档位按这一次的参数升
(ConfirmableTool.escalate):在一张只花钱(ai-cost)的 run_workflow 卡上点了「始终允许」,之后智能体对一张带
HTTP 节点(external,后果在应用之外、撤不回)的工作流开卡,也不问人就跑了。

撤不回的两档(external / destroy)不给这个口子:同一个工具名下,这两档的每一张卡后果各不相同。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentSession, ToolConfirmation, User
from app.domain.agent.autopilot import wait_for_idle_autopilot
from app.domain.jobs import wait_for_idle_jobs
from tests.util import fresh_client

HARMLESS = {
    "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
              {"id": "t", "type": "template", "config": {"template": "x"}}],
    "edges": [{"id": "e", "source": "start", "target": "t"}],
}
OUTWARD = {
    "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
              {"id": "h", "type": "http_request", "config": {"url": "https://example.com/hook", "method": "POST"}}],
    "edges": [{"id": "e", "source": "start", "target": "h"}],
}


class Chat:
    def __init__(self) -> None:
        self.client = fresh_client()
        self.ws = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        self.sid = self.client.post("/api/agent/sessions", json={"workspace_id": self.ws, "title": "T"}).json()["id"]
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            self.token = mint_service_session(db, user.id, agent_session_id=self.sid)

    def workflow(self, name: str, graph: dict) -> str:
        return self.client.post("/api/workflows", json={"workspace_id": self.ws, "name": name, "graph": graph}).json()["id"]

    def run_card(self, workflow_id: str) -> ToolConfirmation:
        """智能体(这一轮的服务凭据)开一张 run_workflow 卡,等自动放行判完。"""
        response = self.client.post(
            "/api/agent/tools/run_workflow",
            json={"arguments": {"workflow_id": workflow_id, "workspace_id": self.ws}, "requested_by": "pi"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        assert response.status_code == 200, response.text
        wait_for_idle_autopilot(timeout=10)
        wait_for_idle_jobs(timeout=10)
        with SessionLocal() as db:
            return db.get(ToolConfirmation, response.json()["result"]["confirmation_id"])

    def allow(self, *entries: dict):
        return self.client.patch(f"/api/agent/sessions/{self.sid}", json={"auto_allow_tools": list(entries)})


def test_在只花钱的那一档点过始终允许_对外的那一档照样问人() -> None:
    chat = Chat()
    harmless, outward = chat.workflow("无害", HARMLESS), chat.workflow("对外", OUTWARD)
    first = chat.run_card(harmless)
    assert (first.permission, first.status) == ("ai-cost", "pending")
    # 用户在这张卡上点「本会话始终允许」:前端先写白名单(工具 + 这张卡的档位)再批准。
    assert chat.allow({"tool": "run_workflow", "permission": first.permission}).status_code == 200
    chat.client.post(f"/api/confirmations/{first.id}/approve")

    again = chat.run_card(harmless)
    assert (again.status, again.decision_mode) == ("executed", "session-allow"), "同一档的照样不再问"

    risky = chat.run_card(outward)
    assert risky.permission == "external"
    assert (risky.status, risky.decision_mode) == ("pending", "manual"), "ai-cost 的允许被拿去放行了对外的那一档"


def test_低一档的允许不覆盖高一档的卡() -> None:
    chat = Chat()
    harmless = chat.workflow("无害", HARMLESS)
    assert chat.allow({"tool": "run_workflow", "permission": "edit"}).status_code == 200
    card = chat.run_card(harmless)
    assert (card.permission, card.status) == ("ai-cost", "pending")


def test_撤不回的两档和不认识的工具_不能设成始终允许() -> None:
    chat = Chat()
    for entry in (
        {"tool": "run_workflow", "permission": "external"},
        {"tool": "delete_assets", "permission": "destroy"},
        {"tool": "run_workflow", "permission": "whatever"},
        {"tool": "no_such_tool", "permission": "edit"},
    ):
        refused = chat.allow(entry)
        assert refused.status_code == 422, (entry, refused.text)
    assert chat.client.get(f"/api/agent/sessions/{chat.sid}").json()["auto_allow_tools"] == []


def test_同一个工具点过两次_留高的那一档() -> None:
    chat = Chat()
    saved = chat.allow(
        {"tool": "run_workflow", "permission": "edit"},
        {"tool": "run_workflow", "permission": "ai-cost"},
        {"tool": "run_workflow", "permission": "edit"},
        {"tool": "edit_timeline", "permission": "edit"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["auto_allow_tools"] == [
        {"tool": "run_workflow", "permission": "ai-cost"},
        {"tool": "edit_timeline", "permission": "edit"},
    ]


def test_迁移把老的工具名转成_工具和声明下限档_撤不回的和认不出的去掉_再跑一次不动() -> None:
    from app.db.migrations import _migrate_session_allow_remembers_the_tier as migrate

    chat = Chat()
    with SessionLocal() as db:
        session = db.get(AgentSession, chat.sid)
        session.auto_allow_tools = [
            "edit_timeline", "run_workflow", "render_sequence", "plugin__conn1__bill",
            "delete_assets", "publish_asset", "run_code", "retired_tool",
            {"tool": "generate_image", "permission": "ai-cost"},
        ]
        db.commit()

    migrate()
    migrate()

    with SessionLocal() as db:
        assert db.get(AgentSession, chat.sid).auto_allow_tools == [
            {"tool": "edit_timeline", "permission": "edit"},
            {"tool": "run_workflow", "permission": "ai-cost"},
            {"tool": "render_sequence", "permission": "render-cost"},
            {"tool": "plugin__conn1__bill", "permission": "edit"},
            {"tool": "generate_image", "permission": "ai-cost"},
        ]


def test_迁移里抄的下限档和此刻的登记表一致() -> None:
    """迁移的身体是冻住的快照;这里只核对写它的这一刻没有抄错(以后登记表变了,改的是新工具,不是这份老数据)。"""
    import inspect

    from app.db import migrations
    from app.domain.agent.autopilot import SESSION_ALLOWABLE
    from app.domain.agent.confirmable import tool_specs

    source = inspect.getsource(migrations._migrate_session_allow_remembers_the_tier)
    for name, spec in tool_specs().items():
        if spec.permission in SESSION_ALLOWABLE:
            assert f'"{name}": "{spec.permission}"' in source, name
        else:
            assert f'"{name}":' not in source, name
