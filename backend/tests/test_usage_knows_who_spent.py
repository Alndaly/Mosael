"""每一笔用量写的时候就记下替谁花的钱(ADR 0050 D30),老账回填找得到的人、找不到的留空(D31)。

此前「谁在花钱」顺着任务找人:智能体对话、画板、工作流节点里的调用不挂任务,维护者库上 94% 的美元花费归不到人。
"""

from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_deployments_keep_finished_jobs_for_a_year as add_retention
from app.db.migrations import _migrate_usage_finds_who_spent_it as backfill
from app.db.migrations import _migrate_usage_remembers_who_spent as add_column
from app.db.models import AgentMessage, AgentSession, GenerationJob, GenerationSession, Job, ProviderUsageEvent, User
from app.domain.billing.usage import billable
from tests.util import fresh_client

BACKEND = Path(__file__).resolve().parents[1]


def test_每个记账的调用点都说替谁花的钱_不写字面量None() -> None:
    """`user_id` 没有默认值,漏了在调用那一刻就报错;这里再静态看一遍,连「先传个 None 凑数」也拦下。"""
    offenders: list[str] = []
    sources = [*(BACKEND / "app").rglob("*.py"), BACKEND / "mcp_server.py"]
    for path in sources:
        tree = ast.parse(path.read_text())
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name not in ("billable", "record_usage"):
                continue
            given = {kw.arg: kw.value for kw in call.keywords}
            where = f"{path.relative_to(BACKEND)}:{call.lineno}"
            if "user_id" not in given:
                offenders.append(f"{where} 没说替谁花的钱")
            elif isinstance(given["user_id"], ast.Constant) and given["user_id"].value is None:
                offenders.append(f"{where} 写了 user_id=None")
    assert not offenders, "\n".join(offenders)


def test_记账时记下替谁花的钱() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter_by(username="tester").one().id
        with billable(db, user_id=me, capability="chat", operation="probe", workspace_id=ws, idempotency_key="probe:me") as call:
            call.meter(requests=1)
        db.commit()
        assert db.query(ProviderUsageEvent).filter_by(idempotency_key="probe:me").one().user_id == me


def _event(db, ws: str, key: str, **facts) -> None:
    db.add(ProviderUsageEvent(workspace_id=ws, capability="chat", operation="x", idempotency_key=key, **facts))


def test_老账回填_顺着任务消息会话找人_找不到的留空_跑两遍和一遍一样() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter_by(username="tester").one().id
        job = Job(workspace_id=ws, kind="render", status="succeeded", created_by=me)
        session = AgentSession(workspace_id=ws, title="会话", owner_user_id=me)
        generation_session = GenerationSession(workspace_id=ws, title="图", owner_user_id=me)
        db.add_all([job, session, generation_session])
        db.flush()
        message = AgentMessage(session_id=session.id, role="assistant", content="好")
        generation = GenerationJob(workspace_id=ws, session_id=generation_session.id, provider="p", model="m", kind="image",
                                   request={"prompt": "x"})
        db.add_all([message, generation])
        db.flush()
        _event(db, ws, "by-job", job_id=job.id)
        _event(db, ws, "by-message", agent_message_id=message.id, source_type="agent_message", source_id=message.id)
        _event(db, ws, "by-message-source", source_type="agent_message", source_id=message.id)
        _event(db, ws, "by-session", source_type="agent_session", source_id=session.id)
        _event(db, ws, "by-generation", source_type="generation_job", source_id=generation.id)
        _event(db, ws, "by-preview", source_type="voice_preview", source_id=me)
        _event(db, ws, "preview-of-nobody", source_type="voice_preview", source_id="gone-user")
        _event(db, ws, "workflow", source_type="workflow", source_id="w1")
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE provider_usage_events DROP COLUMN user_id"))

    add_column()
    backfill()
    add_column()
    backfill()

    with engine.begin() as conn:
        found = dict(conn.execute(text("SELECT idempotency_key, user_id FROM provider_usage_events")).all())
    assert found == {
        "by-job": me, "by-message": me, "by-message-source": me, "by-session": me, "by-generation": me, "by-preview": me,
        "preview-of-nobody": None, "workflow": None,
    }


def test_老库的部署设置补上任务保留天数_默认一年() -> None:
    client = fresh_client()
    #: 老库里那一行部署设置(这里先存一次,行就落下了)
    assert client.put("/api/admin/job-retention", json={"days": 180}).status_code == 200
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config DROP COLUMN job_retention_days"))
    add_retention()
    add_retention()
    with engine.begin() as conn:
        assert [row[0] for row in conn.execute(text("SELECT job_retention_days FROM deployment_config"))] == [365]
