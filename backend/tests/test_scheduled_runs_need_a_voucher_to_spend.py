"""定时任务的担保人(ADR 0047):主人的 AI 连接、插件连接,也只花在主人担保过的那一版图上。

此前私有发布账号 / 浏览器档案 / 本机文件已经要「被执行那一版有人担保」(ADR 0008 §3.8),AI 钥匙和额度却只看跑的人:
同事改了主人的定时任务绑着的图,到点一跑,就以主人的连接花主人的钱。修法:

- 判据同一条:一次运行要用属于某人的连接,被执行的每一版都要有连接的主人做担保人(D7、D9);
- 开跑前查(engine.unvouched_spend,D8),执行时那道闸兜底(domain/authority.ensure_vouched_to_spend);
- 点「运行」/「立即运行」即认可(D6),实际只挡无人看着的运行;
- 别人改了图只提醒、不拦:任务主人收到通知,任务上挂「待你确认」(D10);
- 升级时给每个任务的主人对它此刻跑的那几版补一条认可(D11)。

走真的工作流引擎和 webhook 触发,只把最外面那一次对话请求换成桩(记下用的是谁的连接)。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import (
    Job,
    Notification,
    ScheduledTask,
    ScheduledTaskRun,
    Workflow,
    WorkflowRevision,
    WorkflowRevisionAttestation,
)
from app.domain.workflows import NODE_TYPES
from tests.util import add_provider, fresh_client, second_client, user_id


def _llm_graph(prompt: str = "写一句日报") -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "ask", "type": "llm", "config": {"prompt": prompt}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "ask"}],
    }


def _free_graph(text: str = "早") -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "say", "type": "template", "config": {"template": text}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "say"}],
    }


def _child_graph(prompt: str = "写一句日报") -> dict:
    """被调用的子流程:要花钱(对话节点),并用输出节点把结果交回调用方。"""
    graph = _llm_graph(prompt)
    graph["nodes"].append({"id": "out", "type": "output", "config": {"values": {"text": "{{ask.text}}"}}})
    graph["edges"].append({"id": "e2", "source": "ask", "target": "out"})
    return graph


def _caller_graph(child_id: str) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "call", "type": "call_workflow", "config": {"workflow_id": child_id, "inputs": {}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "call"}],
    }


@pytest.fixture
def team(monkeypatch):
    """主人(tester)和一个编辑同事(mate);主人接了一条对话连接。对话请求换成桩,记下花的是谁的连接。"""
    from app.domain.workflows.executors import ai

    owner = fresh_client()
    mate = second_client("mate")
    workspace = owner.post("/api/workspaces", json={"name": "团队"}).json()
    invitation = owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    assert mate.post(f"/api/invitations/{invitation.json()['id']}/accept").status_code == 200
    with SessionLocal() as db:
        add_provider(db, name="主人的连接", vendor="openai", base_url="https://owner.example/v1", api_key="k",
                     model="chat-owner", capability_ids=["chat"], owner_username="tester")
        add_provider(db, name="同事的连接", vendor="openai", base_url="https://mate.example/v1", api_key="k",
                     model="chat-mate", capability_ids=["chat"], owner_username="mate")
        db.commit()  # 测试是入口:领域函数不提交
    spent: list[str] = []

    def fake_chat(target, messages, **_kw):
        spent.append(target.base_url)
        return "好"

    monkeypatch.setattr(ai, "chat", fake_chat)
    return SimpleNamespace(owner=owner, mate=mate, workspace=workspace, spent=spent)


def _workflow(client: TestClient, workspace_id: str, graph: dict, name: str = "日报") -> dict:
    made = client.post("/api/workflows", json={"workspace_id": workspace_id, "name": name, "graph": graph})
    assert made.status_code == 200, made.text
    return made.json()


def _hooked_task(client: TestClient, workspace_id: str, workflow_id: str) -> dict:
    task = client.post("/api/scheduled-tasks", json={
        "workspace_id": workspace_id, "name": "每天的日报", "kind": "workflow", "trigger_type": "webhook",
        "schedule": {}, "payload": {"workflow_id": workflow_id, "params": {}},
    })
    assert task.status_code == 200, task.text
    return task.json()


def _edit(client: TestClient, workflow_id: str, graph: dict) -> dict:
    current = client.get(f"/api/workflows/{workflow_id}").json()
    changed = client.patch(f"/api/workflows/{workflow_id}", json={"graph": graph, "base_graph_hash": current["graph_hash"]})
    assert changed.status_code == 200, changed.text
    return changed.json()


def _settle(job_id: str) -> tuple[Job, ScheduledTaskRun | None]:
    from app.domain.scheduler.executors import sync_run_states

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            sync_run_states(db)
            db.commit()
            job = db.get(Job, job_id)
            run = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.job_id == job_id).one_or_none()
            if job.status in ("succeeded", "failed") and (run is None or run.status in ("succeeded", "failed")):
                db.expunge(job)
                if run is not None:
                    db.expunge(run)
                return job, run
        time.sleep(0.05)
    raise AssertionError("运行没跑完")


def _fire(client: TestClient, task: dict) -> tuple[Job, ScheduledTaskRun]:
    """webhook 触发:没人看着的那一种。"""
    fired = client.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret={task['webhook_secret']}")
    assert fired.status_code == 200, fired.text
    job, run = _settle(fired.json()["job_id"])
    assert run is not None
    return job, run


def _attested_by(workflow_id: str, revision: int) -> set[str]:
    with SessionLocal() as db:
        row = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id, revision=revision).one()
        return {one.user_id for one in db.query(WorkflowRevisionAttestation).filter_by(revision_id=row.id)}


# ---------------- 无人看着的运行:别人改过的那一版,花主人的钱之前停下 ----------------


def test_a_mates_edit_stops_the_owners_task_before_it_spends(team) -> None:
    workflow = _workflow(team.owner, team.workspace["id"], _llm_graph())
    task = _hooked_task(team.owner, team.workspace["id"], workflow["id"])

    job, _run = _fire(team.owner, task)
    assert job.status == "succeeded", job.error  # 主人自己存的那一版:照旧
    assert team.spent == ["https://owner.example/v1"]

    edited = _edit(team.mate, workflow["id"], _llm_graph("写一句别的"))
    team.spent.clear()
    job, run = _fire(team.owner, task)
    assert job.status == "failed" and job.error_key == "wfErr_spendNotVouched", (job.status, job.error)
    assert team.spent == [], "开跑之前就停下 —— 主人的连接一次都没被调"
    assert job.created_by == user_id("tester"), "跑的人还是任务主人;挡住它的是那一版没有他担保"
    expected = {"workflow_id": workflow["id"], "workflow_name": "日报", "revision": edited["revision"]}
    assert run.result["attest"] == expected, "运行记录上带着是哪一版,任务页据此给「认可这一版」"
    assert job.result["failure"]["details"]["attest"] == expected, "运行历史里同样给得出「认可这一版」"
    with SessionLocal() as db:
        assert db.get(ScheduledTask, task["id"]).enabled, "等认可不是跑不起来:任务照常启用,不被停掉"

    # 同事认可不算数:花的是主人的钱,担保人得是主人。
    assert team.mate.post(f"/api/workflows/{workflow['id']}/revisions/{edited['revision']}/attest").status_code == 200
    job, _run = _fire(team.owner, task)
    assert job.error_key == "wfErr_spendNotVouched"

    approved = team.owner.post(f"/api/workflows/{workflow['id']}/revisions/{edited['revision']}/attest")
    assert approved.status_code == 200, approved.text
    job, _run = _fire(team.owner, task)
    assert job.status == "succeeded", job.error
    assert team.spent == ["https://owner.example/v1"]


def test_a_graph_that_spends_nothing_runs_without_approval(team) -> None:
    """不用任何人连接的图(D7:免费的内置能力不算),同事改过照样到点跑。"""
    workflow = _workflow(team.owner, team.workspace["id"], _free_graph())
    task = _hooked_task(team.owner, team.workspace["id"], workflow["id"])
    _edit(team.mate, workflow["id"], _free_graph("晚"))
    job, _run = _fire(team.owner, task)
    assert job.status == "succeeded", job.error


def test_a_called_workflow_that_spends_needs_the_owner_too(team) -> None:
    """父流程是主人的、不花钱;它调的子流程是同事写的、要花钱 —— 停在子流程那一版,开跑之前。"""
    child = _workflow(team.mate, team.workspace["id"], _child_graph(), name="子流程")
    parent = _workflow(team.owner, team.workspace["id"], _caller_graph(child["id"]), name="父流程")
    task = _hooked_task(team.owner, team.workspace["id"], parent["id"])

    job, run = _fire(team.owner, task)
    assert job.error_key == "wfErr_spendNotVouched", (job.status, job.error)
    assert run.result["attest"]["workflow_id"] == child["id"]
    assert team.spent == []

    team.owner.post(f"/api/workflows/{child['id']}/revisions/{child['revision']}/attest")
    job, _run = _fire(team.owner, task)
    assert job.status == "succeeded", job.error
    assert team.spent == ["https://owner.example/v1"]


def test_a_callee_known_only_at_run_time_answers_for_its_callers_too(team) -> None:
    """子流程名字写成引用:开跑前看不到它,轮到它开跑时同一条再判一次 —— 连同调用它的那一层(同事改的父流程)。
    停在子流程开跑之前,失败现场点名的是父流程那一版。"""
    child = _workflow(team.owner, team.workspace["id"], _child_graph(), name="子流程")
    graph = _caller_graph("{{start.target}}")
    graph["nodes"][0]["config"]["params"] = {"target": child["id"]}
    parent = _workflow(team.mate, team.workspace["id"], graph, name="父流程")
    task = _hooked_task(team.owner, team.workspace["id"], parent["id"])

    job, run = _fire(team.owner, task)
    assert job.status == "failed" and job.error_key == "wfErr_calledWorkflowCannotStart", (job.status, job.error)
    assert run.result["attest"]["workflow_id"] == parent["id"]
    assert team.spent == []
    with SessionLocal() as db:
        assert db.query(Job).filter(Job.parent_job_id == job.id, Job.kind == "workflow").count() == 0, \
            "子流程没开跑:停在开跑之前,不是跑到对话节点才被闸拦下"


# ---------------- 有人看着的运行:点「运行」/「立即运行」即认可(D6) ----------------


def test_clicking_run_now_counts_as_approval(team) -> None:
    workflow = _workflow(team.owner, team.workspace["id"], _llm_graph())
    task = _hooked_task(team.owner, team.workspace["id"], workflow["id"])
    edited = _edit(team.mate, workflow["id"], _llm_graph("改过"))

    ran = team.owner.post(f"/api/scheduled-tasks/{task['id']}/run")
    assert ran.status_code == 200, ran.text
    job, _run = _settle(ran.json()["job"]["id"])
    assert job.status == "succeeded", job.error
    assert user_id("tester") in _attested_by(workflow["id"], edited["revision"])

    # 认可记下了:之后到点的那几次也不再停。
    job, _run = _fire(team.owner, task)
    assert job.status == "succeeded", job.error


def test_clicking_run_in_the_editor_counts_as_approval(team) -> None:
    workflow = _workflow(team.owner, team.workspace["id"], _llm_graph())
    edited = _edit(team.mate, workflow["id"], _llm_graph("改过"))
    ran = team.owner.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}})
    assert ran.status_code == 200, ran.text
    job, _run = _settle(ran.json()["id"])
    assert job.status == "succeeded", job.error
    assert user_id("tester") in _attested_by(workflow["id"], edited["revision"])


def test_an_agent_card_counts_only_when_a_person_approved_it(team) -> None:
    """智能体的「运行工作流」卡:人点了同意就是点了运行;自动放行的是无人看着的运行,不替他认可。"""
    from app.domain.agent.confirmable.automation import _execute_run_workflow
    from app.domain.workflows import WorkflowDomainError

    workflow = _workflow(team.owner, team.workspace["id"], _llm_graph())
    edited = _edit(team.mate, workflow["id"], _llm_graph("改过"))
    payload = {"workflow_id": workflow["id"], "workflow_revision": edited["revision"], "params": {}}
    with SessionLocal() as db:
        with pytest.raises(WorkflowDomainError) as held:
            _execute_run_workflow(db, SimpleNamespace(payload=payload, decision_mode="auto"), user_id("tester"))
        assert held.value.key == "wfErr_spendNotVouched"
        db.rollback()
        started = _execute_run_workflow(db, SimpleNamespace(payload=payload, decision_mode="manual"), user_id("tester"))
        db.commit()
    job, _run = _settle(started["job_id"])
    assert job.status == "succeeded", job.error


# ---------------- 执行时的闸:运行中途才解析到的连接 ----------------


def _inside_a_run_of(workflow_id: str, actor: str):
    """开一条钉着这张图当前版的工作流任务,返回它的 id —— 在它底下解析连接,就是「在这次运行里」。"""
    from app.domain.jobs import create_job
    from app.domain.workflows.revisions import current_workflow_revision

    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        revision = current_workflow_revision(db, workflow)
        job = create_job(db, workspace_id=workflow.workspace_id, kind="workflow", created_by=actor, payload={
            "workflow_id": workflow.id, "workflow_revision_id": revision.id, "workflow_revision": revision.revision,
        })
        db.commit()
        return job.id


def test_resolving_the_owners_connection_mid_run_is_stopped_too(team) -> None:
    from app.db.models import ProviderProfile
    from app.domain.authority import SpendNotVouched
    from app.domain.jobs import reset_parent_job, set_parent_job
    from app.domain.providers import credentials

    workflow = _workflow(team.owner, team.workspace["id"], _free_graph())
    edited = _edit(team.mate, workflow["id"], _free_graph("改过"))
    run_id = _inside_a_run_of(workflow["id"], user_id("tester"))
    with SessionLocal() as db:
        profile = db.query(ProviderProfile).filter_by(name="主人的连接").one()
        # 不在运行里(设置页、单独的一次生成):只看是不是主人,照旧解析。
        assert credentials.resolve_connection(db, profile, user_id("tester")) is not None
        token = set_parent_job(run_id)
        try:
            with pytest.raises(SpendNotVouched) as stopped:
                credentials.resolve_connection(db, profile, user_id("tester"))
        finally:
            reset_parent_job(token)
    assert stopped.value.key == "spendErr_notVouched"
    assert stopped.value.details["attest"] == {"workflow_id": workflow["id"], "workflow_name": "日报",
                                               "revision": edited["revision"]}


def test_a_plugin_connection_is_a_connection_too(team, monkeypatch) -> None:
    """插件连接也归人(付费 GPU / 云,带着他的凭据):工具调用的两条路都先过这道闸。"""
    from app.db.models import PluginInstance
    from app.domain.authority import SpendNotVouched
    from app.domain.jobs import reset_parent_job, set_parent_job
    from app.domain.plugins import instances, tools

    workflow = _workflow(team.owner, team.workspace["id"], _free_graph())
    _edit(team.mate, workflow["id"], _free_graph("改过"))
    run_id = _inside_a_run_of(workflow["id"], user_id("tester"))
    #: 只要一条「主人接的、此刻可用」的连接;闸在找工具、起进程之前,后面的都碰不到。
    instance = SimpleNamespace(id="inst", name="主人的 ComfyUI", owner_user_id=user_id("tester"))
    monkeypatch.setattr(instances, "blocked_reason", lambda _db, _inst: "")
    with SessionLocal() as db:
        real_get = db.get
        monkeypatch.setattr(db, "get", lambda model, ident, **kw: instance if model is PluginInstance else real_get(model, ident, **kw))
        token = set_parent_job(run_id)
        try:
            with pytest.raises(SpendNotVouched):
                tools.invoke(db, "inst", "draw", {})
            with pytest.raises(SpendNotVouched):
                tools.invoke_host(db, "inst", "generation", {})
        finally:
            reset_parent_job(token)


def test_a_child_job_that_hits_the_gate_hands_the_attest_up(team) -> None:
    """生成、配音这些子任务在自己的线程里解析连接:撞上闸的那一句要带着 attest 落在子任务上,工作流才转得上去。"""
    from app.domain.authority import SpendNotVouched, Voucher
    from app.domain.jobs import create_job, run_job_guarded

    with SessionLocal() as db:
        job = create_job(db, workspace_id=team.workspace["id"], kind="generation", created_by=user_id(), payload={})
        db.commit()
        job_id = job.id
    voucher = Voucher(workflow_id="w", workflow_name="W", revision=2, users=frozenset({"someone-else"}))

    def body() -> None:
        raise SpendNotVouched(voucher, connection="主人的连接")

    run_job_guarded(job_id, body)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and job.error_key == "spendErr_notVouched"
        assert job.result["failure"]["details"]["attest"] == {"workflow_id": "w", "workflow_name": "W", "revision": 2}


# ---------------- 别人改了图:只提醒、不拦(D10) ----------------


def test_the_owner_hears_about_a_mates_edit_once_and_the_task_says_so(team) -> None:
    workflow = _workflow(team.owner, team.workspace["id"], _llm_graph())
    task = _hooked_task(team.owner, team.workspace["id"], workflow["id"])

    def reminders() -> list[Notification]:
        with SessionLocal() as db:
            return [row for row in db.query(Notification).filter_by(user_id=user_id("tester"))
                    if (row.payload or {}).get("reminder") == "awaiting_approval"]

    def listed() -> dict:
        rows = team.owner.get("/api/scheduled-tasks", params={"workspace_id": team.workspace["id"]}).json()
        return next(row for row in rows if row["id"] == task["id"])

    assert listed()["awaiting_approval"] is None
    _edit(team.owner, workflow["id"], _llm_graph("主人自己改"))
    assert reminders() == [], "主人自己存的那一版,他就是担保人 —— 不提醒"

    edited = _edit(team.mate, workflow["id"], _llm_graph("同事改"))
    _edit(team.mate, workflow["id"], _llm_graph("同事又改"))  # 编辑器自动保存:改一处就是一版
    sent = reminders()
    assert len(sent) == 1, "同一个任务还有一条没读的,不再发"
    assert sent[0].payload["scheduled_task_id"] == task["id"]
    assert sent[0].link == "#/scheduler"
    assert sent[0].payload["attest"]["revision"] == edited["revision"], "说的是同事第一次改出来的那一版"

    latest = team.owner.get(f"/api/workflows/{workflow['id']}").json()["revision"]
    assert listed()["awaiting_approval"] == {"workflow_id": workflow["id"], "workflow_name": "日报", "revision": latest}

    # 编辑器里提醒改图的人:要谁认可。主人看到的是他自己的任务。
    for_mate = team.mate.get(f"/api/workflows/{workflow['id']}/awaiting-approvals").json()
    assert [(row["task_id"], row["is_mine"], row["owner_name"]) for row in for_mate] == [(task["id"], False, "tester")]
    for_owner = team.owner.get(f"/api/workflows/{workflow['id']}/awaiting-approvals").json()
    assert [(row["task_id"], row["is_mine"]) for row in for_owner] == [(task["id"], True)]

    # 读了之后同事再改,再提醒一次。
    with SessionLocal() as db:
        from app.db.models import now

        for row in db.query(Notification).filter_by(user_id=user_id("tester")):
            row.read_at = now()
        db.commit()
    _edit(team.mate, workflow["id"], _llm_graph("同事第三次改"))
    assert len(reminders()) == 2

    # 停用的任务不会到点跑,也就不挂「待你确认」。
    assert team.owner.patch(f"/api/scheduled-tasks/{task['id']}", json={"enabled": False}).status_code == 200
    assert listed()["awaiting_approval"] is None
    assert team.owner.patch(f"/api/scheduled-tasks/{task['id']}", json={"enabled": True}).status_code == 200
    assert listed()["awaiting_approval"] is not None

    latest = team.owner.get(f"/api/workflows/{workflow['id']}").json()["revision"]
    team.owner.post(f"/api/workflows/{workflow['id']}/revisions/{latest}/attest")
    assert listed()["awaiting_approval"] is None
    assert team.mate.get(f"/api/workflows/{workflow['id']}/awaiting-approvals").json() == []


def test_a_callers_task_hears_about_the_called_workflow(team) -> None:
    """改的是被调用的子流程:绑着调用它的那张图的任务一样要等主人认可、一样提醒。"""
    child = _workflow(team.owner, team.workspace["id"], _child_graph(), name="子流程")
    parent = _workflow(team.owner, team.workspace["id"], _caller_graph(child["id"]), name="父流程")
    task = _hooked_task(team.owner, team.workspace["id"], parent["id"])
    edited = _edit(team.mate, child["id"], _child_graph("同事改子流程"))
    with SessionLocal() as db:
        sent = [row for row in db.query(Notification).filter_by(user_id=user_id("tester"))
                if (row.payload or {}).get("reminder") == "awaiting_approval"]
    assert [row.payload["scheduled_task_id"] for row in sent] == [task["id"]]
    rows = team.mate.get(f"/api/workflows/{child['id']}/awaiting-approvals").json()
    assert [(row["task_id"], row["awaiting"]["workflow_id"], row["awaiting"]["revision"]) for row in rows] == [
        (task["id"], child["id"], edited["revision"])
    ]

    # 主人自己改父流程:任务还在等子流程那一版,但他自己存的这一版不该给他自己发提醒(任务卡上看得见)。
    with SessionLocal() as db:
        from app.db.models import now

        for row in db.query(Notification).filter_by(user_id=user_id("tester")):
            row.read_at = now()
        db.commit()
    graph = _caller_graph(child["id"])
    graph["nodes"].append({"id": "say", "type": "template", "config": {"template": "主人加的一步"}})
    graph["edges"].append({"id": "e2", "source": "call", "target": "say"})
    saved = _edit(team.owner, parent["id"], graph)
    assert saved["revision"] == parent["revision"] + 1, "这一下真的存出了新的一版"
    with SessionLocal() as db:
        again = [row for row in db.query(Notification).filter_by(user_id=user_id("tester"))
                 if (row.payload or {}).get("reminder") == "awaiting_approval"]
    assert len(again) == 1, "主人自己存的不提醒他自己"


# ---------------- 升级(D11) ----------------


def test_upgrading_vouches_for_what_each_task_runs_today(team) -> None:
    """升级前任务就是这样在跑的:迁移给主人对绑着的那张图、和它调用的子流程的当前版各记一条认可。重跑不重复记。"""
    from app.db.migrations import _migrate_scheduled_tasks_vouch_for_what_they_run as migrate

    child = _workflow(team.mate, team.workspace["id"], _child_graph(), name="子流程")
    parent = _workflow(team.mate, team.workspace["id"], _caller_graph(child["id"]), name="父流程")
    task = _hooked_task(team.owner, team.workspace["id"], parent["id"])
    job, _run = _fire(team.owner, task)
    assert job.error_key == "wfErr_spendNotVouched", "迁移之前:同事写的那两版没有主人担保"

    migrate()
    assert user_id("tester") in _attested_by(parent["id"], parent["revision"])
    assert user_id("tester") in _attested_by(child["id"], child["revision"])
    with SessionLocal() as db:
        before = db.query(WorkflowRevisionAttestation).count()
    migrate()
    with SessionLocal() as db:
        assert db.query(WorkflowRevisionAttestation).count() == before

    job, _run = _fire(team.owner, task)
    assert job.status == "succeeded", job.error


# ---------------- 棘轮 ----------------


def test_every_node_type_says_whether_it_spends_someones_connection() -> None:
    """新节点必须说清它会不会用某人的连接:漏写就红,而不是悄悄按「不花钱」处理(那样别人改过的图会花主人的钱)。"""
    missing = [name for name, spec in NODE_TYPES.items() if not isinstance(spec.get("spends"), bool)]
    assert not missing, f"这些节点没声明 \"spends\": True/False:{missing}"


def test_plugin_nodes_always_count_as_spending() -> None:
    from app.domain.workflows.graph_rules import spending_nodes_in_graph

    graph = {"nodes": [{"id": "p", "type": "plugin.comfyui.draw", "config": {}},
                       {"id": "loop", "type": "loop_foreach", "config": {"body": {"nodes": [
                           {"id": "inner", "type": "ai_generate", "config": {}}]}}}]}
    assert spending_nodes_in_graph(graph) == {"plugin.comfyui.draw", "ai_generate"}, "插件节点、循环体里的都算"


def test_the_assembly_root_wires_the_run_authority_into_the_gate() -> None:
    """闸自己从任务上下文取「这次运行的授权」;没接上时它当作不在任何运行里 —— 那就等于没有闸。"""
    import app.main  # noqa: F401 — 组装根在导入期接线
    from app.domain import authority
    from app.domain.workflows.authority import current_authority

    assert authority._run_authority is current_authority


@pytest.mark.parametrize("source", ["migration", "rename"])
def test_a_mechanical_rewrite_keeps_the_vouchers_and_reminds_nobody(team, source) -> None:
    """机械改写(升级迁移;在工作流库里改名时引用跟着改,ADR 0045 修订之二)沿用上一版的作者和认可,不提醒谁去认可 ——
    此前只认 `migration`:改名落的那一版以上一版作者的名义告诉任务主人「存了新的一版、等你认可」,而谁都没改过这张图。"""
    from app.domain.workflows.plugin_references import _commit_mechanical_revision
    from app.domain.workflows.revisions import current_workflow_revision, revision_vouchers

    workflow = _workflow(team.owner, team.workspace["id"], _llm_graph())
    _hooked_task(team.owner, team.workspace["id"], workflow["id"])
    _edit(team.mate, workflow["id"], _llm_graph("同事改"))

    def reminders() -> list[Notification]:
        with SessionLocal() as db:
            return [row for row in db.query(Notification).filter_by(user_id=user_id("tester"))
                    if (row.payload or {}).get("reminder") == "awaiting_approval"]

    assert len(reminders()) == 1
    with SessionLocal() as db:
        from app.db.models import now

        for row in db.query(Notification).filter_by(user_id=user_id("tester")):
            row.read_at = now()
        db.commit()

    def rewrite(graph: dict) -> dict:
        graph["nodes"][1]["config"]["prompt"] = "同事改(机械改写过)"
        return graph

    with SessionLocal() as db:
        row = db.get(Workflow, workflow["id"])
        before = revision_vouchers(db, current_workflow_revision(db, row))
        assert _commit_mechanical_revision(db, row, rewrite, "机械改写", source=source)
        db.commit()
        after = current_workflow_revision(db, row)
        assert after.source == source and revision_vouchers(db, after) == before
    assert len(reminders()) == 1, "机械改写不提醒"
