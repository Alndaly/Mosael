"""对话记住在哪开的(ADR 0044 §1)的迁移:加「家」、把记着的事实转成家(`_migrate_agent_sessions_remember_where_they_were_opened`),
再重建这张表删掉带外键的 `project_id`(`_drop_agent_sessions_project_id` → `_rebuild_dropping`);以及维护者 2026-10-07 的修订:
名字是谁起的(`_migrate_agent_sessions_know_who_named_them`)、删掉从没说过话的空对话(`_drop_empty_agent_sessions`)。

**重建删列时一条都不能少。** `agent_messages.session_id` 是 `ON DELETE CASCADE`:不关外键就删旧表,全部消息跟着走;跟着消息的
用量记录、技能上记着的「在哪次对话里建的」被置空。所以这里拿老形状的库(带 `project_id` 外键、`origin='workflow'` 的行),挂上
消息(含排队的)、用量、确认卡、选择卡、技能、登录会话、共享记录,跑完逐样数一遍。
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.security import mint_service_session
from app.db.migrations import (
    _drop_agent_sessions_project_id,
    _drop_dead_agent_session_columns,
    _drop_empty_agent_sessions,
    _migrate_agent_sessions_know_who_named_them,
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

#: ADR 0044 之前的那张表:`project_id` 外键到 projects,没有家。从 Alembic 0008 那一代升上来的库里还带着两列死列:
#: `adapter_session_id`(claude 适配器的,`4a2e51e4b` 删了读写)和没删掉的 `sort_order` —— 重建之前得先删掉它们。
_OLD_TABLE = """
CREATE TABLE agent_sessions (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    owner_user_id VARCHAR(64),
    project_id VARCHAR(64) REFERENCES projects(id) ON DELETE SET NULL,
    adapter_session_id VARCHAR(120),
    sort_order INTEGER NOT NULL DEFAULT 0,
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
        _old_session(conn, "plain", workspace, owner_user_id=me, adapter_session_id="claude-resume-1", sort_order=3)
        _old_session(conn, "in-project", workspace, owner_user_id=me, project_id=project)
        _old_session(conn, "wf-default", workspace, origin="workflow", external_key=f"workflow:{workflow}")
        _old_session(conn, "wf-second", workspace, origin="workflow", external_key=f"workflow:{workflow}:ab12cd34",
                     owner_user_id=me)
        _old_session(conn, "wf-gone", workspace, origin="workflow", external_key="workflow:deadbeef")
        # 从没说过话的:一段点「新对话」建的(还共享出去了)、一段死路由建的。
        _old_session(conn, "empty", workspace, owner_user_id=me, title="新对话")
        _old_session(conn, "wf-empty", workspace, origin="workflow", external_key=f"workflow:{workflow}:ffff0000")
        # 没有消息、但挂着别的东西的:不算空。
        _old_session(conn, "only-card", workspace, owner_user_id=me, title="新对话")
        _old_session(conn, "only-question", workspace, owner_user_id=me, title="新对话")
        _old_session(conn, "only-usage", workspace, owner_user_id=me, title="新对话")
        _old_session(conn, "only-skill", workspace, owner_user_id=me, title="新对话")
        # 说过话、却还叫「新对话」的(只收到过别的对话的通知):名字还由我们起。
        _old_session(conn, "untitled", workspace, owner_user_id=me, title="新对话")
        # 飞书的会话不进界面清单,空的也不碰。
        _old_session(conn, "feishu-empty", workspace, origin="feishu", external_key="feishu:bot:chat", title="飞书 · 机器人")
        conn.commit()

    sessions = ["plain", "in-project", "wf-default", "wf-second", "wf-gone", "untitled"]
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
        db.add(ResourceShare(kind="agent_session", resource_id="empty", workspace_id=workspace, shared_by=me))
        db.add(ProviderUsageEvent(workspace_id=workspace, capability="chat", operation="agent_skill_draft",
                                  source_type="agent_session", source_id="only-usage", idempotency_key="draft:only-usage"))
        db.add(AgentSkill(workspace_id=workspace, source="workspace", name="drafted", origin="agent",
                          agent_session_id="only-skill"))
        db.commit()
        request_confirmation(db, workspace_id=workspace, tool="browser_open", payload={"url": "https://example.com"},
                             actor_id=me, session_id="only-card")
        agent_questions.ask(db, workspace_id=workspace, session_id="only-question",
                            questions=[{"question": "选哪个?", "options": [{"label": "甲"}, {"label": "乙"}]}])
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


#: 从没说过话的那两段 —— 迁移删的就是它们,别的一段都不删。
EMPTY = {"empty", "wf-empty"}


def _migrate() -> None:
    """照迁移计划里的次序:两步在 SCHEMA 之前,三步在之后。"""
    _migrate_agent_sessions_remember_where_they_were_opened()
    _migrate_agent_sessions_know_who_named_them()
    _drop_dead_agent_session_columns()
    _drop_agent_sessions_project_id()
    _drop_empty_agent_sessions()


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


def test_重建删掉_project_id_之后_挂在对话上的东西一样都没少_只少了从没说过话的那两段() -> None:
    old = _old_library()
    before = _counts()
    with engine.connect() as conn:
        sessions_before = {row[0] for row in conn.execute(text("SELECT id FROM agent_sessions"))}

    _migrate()

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
        assert not columns & {"project_id", "adapter_session_id", "sort_order"}, "死列和 project_id 都没了"
        assert {"home_kind", "home_id", "pending_view_at"} <= columns
        indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(agent_sessions)"))}
        assert "idx_agent_sessions_ws_home" in indexes and "idx_agent_sessions_ws_updated" in indexes
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == [], "外键检查干净"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1, "外键开回来了"
    assert set(_homes()) == sessions_before - EMPTY, "说过话的、挂着卡 / 选择卡 / 用量 / 技能的、飞书的,一段都没少"
    assert _counts() == {**before, "agent_sessions": before["agent_sessions"] - len(EMPTY),
                         "resource_shares": before["resource_shares"] - 1}, (
        "别的一行都没少:消息(含排队的)、用量、技能、确认卡、选择卡;共享只少了那段空对话的"
    )
    with SessionLocal() as db:
        usage = db.query(ProviderUsageEvent).filter(ProviderUsageEvent.idempotency_key == "agent-message:in-project-a").one()
        assert usage.agent_message_id == "in-project-a", "跟着消息的用量没被置空"
        skills = {skill.name: skill.agent_session_id for skill in db.query(AgentSkill)}
        assert skills == {"brand": "in-project", "drafted": "only-skill"}, "技能上记着的对话没被置空"
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
    assert steps["migrate-agent-sessions-know-who-named-them"].phase.name == "BEFORE_SCHEMA"
    assert steps["drop-agent-sessions-project-id"].phase.name == "AFTER_SCHEMA"
    assert steps["drop-empty-agent-sessions"].phase.name == "AFTER_SCHEMA"
    order = [step.name for step in migration_plan().steps]
    assert order.index("drop-dead-agent-session-columns") < order.index("drop-agent-sessions-project-id")
    assert order.index("drop-agent-sessions-project-id") < order.index("drop-empty-agent-sessions")


def test_重建认不出的列就不动手_死列要先点名删掉() -> None:
    """守卫照旧:模型上没有、又没点名的列(可能是谁的数据)让重建拒绝动手,库原样不动。"""
    _old_library()
    _migrate_agent_sessions_remember_where_they_were_opened()
    _migrate_agent_sessions_know_who_named_them()
    before = _counts()
    with pytest.raises(RuntimeError, match="adapter_session_id"):
        _drop_agent_sessions_project_id()
    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(agent_sessions)"))}
        assert {"project_id", "adapter_session_id"} <= columns, "拒绝时一点没动"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    assert _counts() == before

    _drop_dead_agent_session_columns()
    _drop_agent_sessions_project_id()
    assert _counts() == before


def test_老对话的名字一律当人起的_还叫新对话的留给我们起() -> None:
    _old_library()
    _migrate()
    with engine.connect() as conn:
        sources = dict(conn.execute(text("SELECT id, title_source FROM agent_sessions")).all())
    assert sources["plain"] == sources["in-project"] == sources["feishu-empty"] == "manual"
    assert sources["untitled"] == sources["only-card"] == "auto"


def test_新库上什么都不做() -> None:
    fresh_client()
    before = _counts()
    _migrate()
    assert _counts() == before
