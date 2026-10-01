"""别的成员建的图(节点上钉着他的对话连接),换个人跑:用跑的人自己的默认对话连接,不是报「没有可用的 AI 供应商」。

官方模板建图时按建图的人挑好连接、钉在 LLM 节点和逐句翻译节点上。连接按人隔离,别的成员跑时那条连接查不到,
此前翻译报「没有可用的 AI 供应商」、LLM 节点报「供应商配置不存在或已停用」—— 他明明接了自己的连接。
走真的工作流引擎,只把最外面那一次对话请求换成桩(记下用的是哪条连接、哪个模型)。
"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.core.i18n import t
from app.db.models import Job, ProviderProfile, Workflow
from app.domain.workflows import create_workflow
from app.domain.workflows.engine import start_workflow_job
from tests.util import add_provider, fresh_client, second_client, user_id


@pytest.fixture
def team(monkeypatch):
    from app.domain import translate as translate_domain
    from app.domain.workflows.executors import ai

    owner = fresh_client()
    member = second_client("other")
    ws = owner.post("/api/workspaces", json={"name": "团队"}).json()["id"]
    invitation = owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "other", "role": "editor"})
    assert member.post(f"/api/invitations/{invitation.json()['id']}/accept").status_code == 200
    with SessionLocal() as db:
        mine = add_provider(db, name="建图人的连接", vendor="openai", base_url="https://a.example/v1", api_key="k",
                            model="chat-a", capability_ids=["chat"], owner_username="tester")
        theirs = add_provider(db, name="成员的连接", vendor="openai", base_url="https://b.example/v1", api_key="k",
                              model="chat-b", capability_ids=["chat"], owner_username="other")
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {"id": "ask", "type": "llm", "config": {"profile_id": mine.id, "model": "chat-a", "prompt": "你好"}},
                {"id": "tr", "type": "translate_lines", "config": {"texts": ["Hello"], "target_lang": "zh-CN",
                                                                 "engine": "builtin:chat", "profile_id": mine.id,
                                                                 "model": "chat-a"}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "ask"}, {"id": "e2", "source": "ask", "target": "tr"}],
        }
        workflow = create_workflow(db, workspace_id=ws, name="建图人建的", graph=graph, created_by=user_id())
        db.commit()
        workflow_id, theirs_id = workflow.id, theirs.id

    used: list[tuple[str, str]] = []

    def fake_chat(target, messages, **_kw):
        used.append((target.base_url, target.model))
        return "好"

    monkeypatch.setattr(ai, "chat", fake_chat)
    monkeypatch.setattr(translate_domain, "chat", fake_chat)

    def run_as_member() -> Job:
        with SessionLocal() as db:
            job_id = start_workflow_job(db, db.get(Workflow, workflow_id), created_by=user_id("other")).id
            db.commit()  # 测试是入口:任务在起它的那次事务提交之后才派发
        for _ in range(200):
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job.status in ("succeeded", "failed", "cancelled"):
                    return job
            time.sleep(0.05)
        raise AssertionError("工作流没跑完")

    return run_as_member, used, theirs_id


def test_成员跑别人建的图_用他自己的默认对话连接和模型(team) -> None:
    run_as_member, used, _ = team
    job = run_as_member()
    assert job.status == "succeeded", job.error
    assert used and set(used) == {("https://b.example/v1", "chat-b")}, \
        "LLM 节点和逐句翻译都换成跑的人自己的连接,模型也跟着换(建图人那个模型名是他那条连接上的)"


def test_成员自己没有对话连接_说清楚那条连接是别人的(team) -> None:
    run_as_member, used, theirs_id = team
    with SessionLocal() as db:
        db.delete(db.get(ProviderProfile, theirs_id))
        db.commit()
    job = run_as_member()
    assert job.status == "failed" and t("providerErr_pinnedNotYours", "zh") in (job.error or ""), (job.status, job.error)
    assert used == [], "建图人的连接一次都没被拿来花钱"


def test_翻译_成员自己没有对话连接_说清楚那条连接是别人的() -> None:
    from app.domain.translate import TranslateError, resolve_ai_chat_target

    fresh_client()
    second_client("other")
    with SessionLocal() as db:
        mine = add_provider(db, name="建图人的连接", vendor="openai", base_url="https://a.example/v1", api_key="k",
                            model="chat-a", capability_ids=["chat"], owner_username="tester")
        with pytest.raises(TranslateError) as refused:
            resolve_ai_chat_target(db, mine.id, user_id("other"), "chat-a", surface="automation")
    assert refused.value.key == "translateErr_pinnedNotYours"
