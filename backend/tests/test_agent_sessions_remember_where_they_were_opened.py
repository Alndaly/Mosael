"""对话记住在哪开的(ADR 0044 §1)的两步迁移:加「家」、把记着的事实转成家(`_migrate_agent_sessions_remember_where_they_were_opened`),
再重建这张表删掉带外键的 `project_id`(`_drop_agent_sessions_project_id` → `_rebuild_dropping`)。

**重建删列时一条都不能少。** `agent_messages.session_id` 是 `ON DELETE CASCADE`:不关外键就删旧表,全部消息跟着走;跟着消息的
用量记录、技能上记着的「在哪次对话里建的」被置空。所以这里拿老形状的库(带 `project_id` 外键、`origin='workflow'` 的行),挂上
消息(含排队的)、用量、确认卡、选择卡、技能、登录会话、共享记录,跑完逐样数一遍。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.security import mint_service_session
from app.db.migrations import (
    _drop_agent_sessions_project_id,
    _migrate_agent_sessions_remember_where_they_were_opened,
    migration_plan,
)
from app.db.models import (
    AgentMessage,
    AgentSkill,
    AuthSession,
    ProviderUsageEvent,
    ResourceShare,
    ToolConfirmation,
    WorkflowRevision,
)
from app.domain.agent import questions as agent_questions
from app.domain.agent.confirmations import request_confirmation
from tests.util import fresh_client, second_client, user_id

#: ADR 0044 之前的那张表:`project_id` 外键到 projects,没有家。
_OLD_TABLE = """
CREATE TABLE agent_sessions (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_user_id VARCHAR(64),
    project_id VARCHAR(64) REFERENCES projects(id) ON DELETE SET NULL,
    group_id VARCHAR(64),
    title VARCHAR(200) NOT NULL,
    origin VARCHAR(24) NOT NULL,
    pending_view VARCHAR(96) NOT NULL DEFAULT '',
    external_key VARCHAR(200) UNIQUE,
    adapter VARCHAR(40) NOT NULL,
    provider_profile_id VARCHAR(64) REFERENCES provider_profiles(id) ON DELETE SET NULL,
    model VARCHAR(120),
    analysis_video_mode VARCHAR(16) NOT NULL,
    permission_mode VARCHAR(16) NOT NULL DEFAULT 'manual',
    mode_set_by VARCHAR(64),
    mode_set_at DATETIME,
    auto_allow_tools JSON NOT NULL DEFAULT '[]',
    thinking_level VARCHAR(10) NOT NULL DEFAULT 'off',
    plan JSON,
    adapter_state JSON,
    status VARCHAR(24) NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""


def _old_session(conn: sqlite3.Connection, session_id: str, workspace: str, **fields: Any) -> None:
    row = {
        "id": session_id, "workspace_id": workspace, "owner_user_id": None, "project_id": None, "title": session_id,
        "origin": "ui", "external_key": None, "adapter": "pi", "analysis_video_mode": "auto", "status": "idle",
        "created_at": "2026-10-01 00:00:00", "updated_at": "2026-10-01 00:00:00", **fields,
    }
    names = ", ".join(row)
    conn.execute(f"INSERT INTO agent_sessions ({names}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))


def _old_library() -> dict[str, Any]:
    """一个老形状的库:四段对话(普通的、剪辑项目里开的、死路由给工作流建的两段、工作流已删的一段),每段都挂着东西。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": workspace, "name": "宣传片"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": workspace, "name": "出海流程"}).json()["id"]
    me = user_id()
    second_client("maker")
    maker = user_id("maker")
    with SessionLocal() as db:
        # 「工作流的创建者」= 最早一版里有记录的作者。换成另一个人,才看得出主人是从工作流认的,不是工作区 owner。
        for revision in db.query(WorkflowRevision).filter(WorkflowRevision.workflow_id == workflow):
            revision.created_by = maker
        db.commit()

    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DROP TABLE agent_sessions")
        conn.execute(_OLD_TABLE)
        _old_session(conn, "plain", workspace, owner_user_id=me)
        _old_session(conn, "in-project", workspace, owner_user_id=me, project_id=project)
        _old_session(conn, "wf-default", workspace, origin="workflow", external_key=f"workflow:{workflow}")
        _old_session(conn, "wf-second", workspace, origin="workflow", external_key=f"workflow:{workflow}:ab12cd34",
                     owner_user_id=me)
        _old_session(conn, "wf-gone", workspace, origin="workflow", external_key="workflow:deadbeef")
        conn.commit()

    sessions = ["plain", "in-project", "wf-default", "wf-second", "wf-gone"]
    with SessionLocal() as db:
        for sid in sessions:
            db.add(AgentMessage(id=f"{sid}-u", session_id=sid, role="user", content="在吗", payload={}))
            db.add(AgentMessage(id=f"{sid}-a", session_id=sid, role="assistant", content="在", payload={}))
        db.add(AgentMessage(id="queued", session_id="plain", role="user", content="排着的",
                            payload={"queued": True, "queued_by": me}))
        db.add(ProviderUsageEvent(workspace_id=workspace, capability="chat", operation="agent_turn",
                                  agent_message_id="in-project-a", idempotency_key="agent-message:in-project-a"))
        db.add(AgentSkill(workspace_id=workspace, source="workspace", name="brand", origin="agent",
                          agent_session_id="in-project"))
        db.add(ResourceShare(kind="agent_session", resource_id="plain", workspace_id=workspace, shared_by=me))
        db.commit()
        card = request_confirmation(db, workspace_id=workspace, tool="browser_open", payload={"url": "https://example.com"},
                                    actor_id=me, session_id="plain")
        agent_questions.ask(db, workspace_id=workspace, session_id="in-project",
                            questions=[{"question": "选哪个?", "options": [{"label": "甲"}, {"label": "乙"}]}])
        db.commit()
        token = mint_service_session(db, me, agent_session_id="wf-second")
        db.commit()
    return {"workspace": workspace, "project": project, "workflow": workflow, "me": me, "maker": maker,
            "card": card.id, "token": token}


def _counts() -> dict[str, int]:
    with engine.connect() as conn:
        return {
            table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
            for table in ("agent_sessions", "agent_messages", "provider_usage_events", "agent_skills",
                          "tool_confirmations", "agent_questions", "resource_shares")
        }


def _homes() -> dict[str, tuple[Any, ...]]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, home_kind, home_id, origin, external_key, owner_user_id FROM agent_sessions"
        )).all()
    return {row[0]: tuple(row[1:]) for row in rows}


def _migrate() -> None:
    _migrate_agent_sessions_remember_where_they_were_opened()
    _drop_agent_sessions_project_id()


def test_老对话的家_普通的在_AI_Studio_带项目的在那个项目_工作流那批成了能看见的对话() -> None:
    old = _old_library()
    _migrate()

    homes = _homes()
    assert homes["plain"] == ("studio", "", "ui", None, old["me"])
    assert homes["in-project"] == ("project", old["project"], "ui", None, old["me"])
    # 死路由那批:origin 改成 ui、家是那个工作流、external_key 清掉;没有主人的记成工作流的创建者。
    assert homes["wf-default"] == ("workflow", old["workflow"], "ui", None, old["maker"])
    assert homes["wf-second"] == ("workflow", old["workflow"], "ui", None, old["me"]), "已经有主人的不改"
    assert homes["wf-gone"][:4] == ("workflow", "deadbeef", "ui", None)
    assert homes["wf-gone"][4] == old["me"], "工作流删了:主人记成工作区的 owner"


def test_重建删掉_project_id_之后_挂在对话上的东西一样都没少() -> None:
    old = _old_library()
    before = _counts()

    _migrate()

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
        assert "project_id" not in columns
        assert {"home_kind", "home_id", "pending_view_at"} <= columns
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(agent_sessions)"))}
        assert "idx_agent_sessions_ws_home" in indexes and "idx_agent_sessions_ws_updated" in indexes
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == [], "外键检查干净"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1, "外键开回来了"
    assert _counts() == before, "一行都没少:消息(含排队的)、用量、技能、确认卡、选择卡、共享"
    with SessionLocal() as db:
        assert db.get(ProviderUsageEvent, db.query(ProviderUsageEvent.id).scalar()).agent_message_id == "in-project-a"
        assert db.query(AgentSkill).one().agent_session_id == "in-project", "技能上记着的对话没被置空"
        assert db.get(ToolConfirmation, old["card"]).session_id == "plain"
        assert db.get(AgentMessage, "queued").payload["queued"] is True
        assert db.query(AuthSession).filter(AuthSession.agent_session_id == "wf-second").count() == 1


def test_再跑一遍什么都不变_两步都在迁移计划里() -> None:
    _old_library()
    _migrate()
    homes, counts = _homes(), _counts()

    _migrate()

    assert _homes() == homes and _counts() == counts
    steps = {step.name: step for step in migration_plan().steps}
    assert steps["migrate-agent-sessions-remember-where-they-were-opened"].phase.name == "BEFORE_SCHEMA"
    assert steps["drop-agent-sessions-project-id"].phase.name == "AFTER_SCHEMA"


def test_新库上什么都不做() -> None:
    fresh_client()
    before = _counts()
    _migrate()
    assert _counts() == before
