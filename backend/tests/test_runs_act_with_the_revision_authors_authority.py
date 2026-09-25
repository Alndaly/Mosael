"""一次运行用私有的东西,要**点运行的人**和**被执行那一版图的担保人**都过得了闸。

此前特权检查只看运行的 actor。工作流是工作区内容、同事能改,而主人的定时任务替主人跑:同事改了
主人的图,到点一跑,那次运行就以主人的授权用主人的私有账号 / 档案 / 本机文件 —— 借别人的任务
用别人的东西。

修法(见 domain/authority):每一版修订记作者(`created_by` 必填,老数据由迁移补上),节点里
`actor=` 传的是这次运行的 `Authority` —— 跑的人,加上被执行的每一版(含 call_workflow 调起的子流程
那一版)的担保人。担保人 = 作者 + 事后「认可这一版」的人;认可不改图、不增版。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import inspect
import pathlib
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import Job, ScheduledTaskRun, User, Workflow
from app.domain import browser, sharing, workflows
from app.domain.workflows import revisions
from tests.util import fresh_client, second_client

#: 落修订的入口。每一个都必须有一个**必填**的关键字参数 `created_by`。
REVISION_WRITERS = {
    "create_workflow": workflows.create_workflow,
    "update_workflow": workflows.update_workflow,
    "edit_workflow_graph": workflows.edit_workflow_graph,
    "commit_graph_revision": revisions.commit_graph_revision,
    "create_initial_revision": revisions.create_initial_revision,
    "restore_workflow_revision": revisions.restore_workflow_revision,
}

#: 用私有资源的闸门。工作流执行器里调它们时,`actor=` 必须是这次运行的 Authority。
SEAMS = {"start_publish", "open_session", "attach_session", "usable_profile", "ensure_readable", "ensure_whole_machine"}


def _name(func: ast.expr) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


# ---------------- 棘轮:形状 ----------------


@pytest.mark.parametrize("name", sorted(REVISION_WRITERS))
def test_every_revision_names_its_author(name: str) -> None:
    param = inspect.signature(REVISION_WRITERS[name]).parameters.get("created_by")
    assert param is not None and param.kind is inspect.Parameter.KEYWORD_ONLY, name
    assert param.default is inspect.Parameter.empty, f"{name} 的 created_by 有默认值 —— 漏写作者的那一版没人担保"


def test_every_caller_writes_a_real_author() -> None:
    paths = [*sorted(pathlib.Path("app").rglob("*.py")), pathlib.Path("mcp_server.py")]
    bad, seen = [], 0
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _name(node.func) in REVISION_WRITERS:
                seen += 1
                author = next((kw for kw in node.keywords if kw.arg == "created_by"), None)
                if author is None or (isinstance(author.value, ast.Constant) and author.value.value is None):
                    bad.append(f"{path}:{node.lineno}")
    assert seen, "一个调用点都没扫到 —— 扫描本身坏了"
    assert not bad, "这些地方存修订没写作者:\n  " + "\n  ".join(bad)


def test_executors_pass_the_runs_authority_not_just_the_actor() -> None:
    """执行器里 `actor=current_actor(db)` 正是「只看跑的人」—— 被执行那一版的作者漏掉了。"""
    bad, seen = [], 0
    for path in sorted(pathlib.Path("app/domain/workflows/executors").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and _name(node.func) in SEAMS):
                continue
            seen += 1
            actor = next((kw.value for kw in node.keywords if kw.arg == "actor"), None)
            if isinstance(actor, ast.Call) and _name(actor.func) != "current_authority":
                bad.append(f"{path}:{node.lineno}")
        if any(isinstance(n, ast.Call) and _name(n.func) in SEAMS for n in ast.walk(tree)):
            assert "current_authority" in path.read_text(encoding="utf-8"), f"{path} 用了闸却没取 current_authority"
    assert seen, "一个调用点都没扫到 —— 扫描本身坏了"
    assert not bad, "这些执行器只传了跑的人:\n  " + "\n  ".join(bad)


# ---------------- 行为 ----------------


def _team() -> tuple[TestClient, dict, TestClient]:
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


def _uid(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _profile(client: TestClient, workspace_id: str) -> str:
    made = client.post("/api/browser/profiles", json={"workspace_id": workspace_id, "name": "主人的浏览器"})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _graph(profile_id: str, session_name: str = "") -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {
                "id": "open", "type": "browser_open",
                "config": {"session_mode": "pool", "profile_id": profile_id, "session_name": session_name},
            },
        ],
        "edges": [{"id": "e1", "source": "start", "target": "open"}],
    }


def _hooked(client: TestClient, workspace_id: str, profile_id: str) -> tuple[dict, dict]:
    workflow = client.post("/api/workflows", json={"workspace_id": workspace_id, "name": "钩子", "graph": _graph(profile_id)})
    assert workflow.status_code == 200, workflow.text
    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": workspace_id, "name": "钩子任务", "kind": "workflow", "trigger_type": "webhook",
            "schedule": {}, "payload": {"workflow_id": workflow.json()["id"], "params": {}},
        },
    ).json()
    return workflow.json(), task


def _fire(client: TestClient, task: dict) -> tuple[Job, ScheduledTaskRun]:
    fired = client.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret={task['payload']['webhook_secret']}")
    assert fired.status_code == 200, fired.text
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            from app.domain.scheduler.executors import sync_run_states

            sync_run_states(db)
            job = db.get(Job, fired.json()["job_id"])
            run = db.query(ScheduledTaskRun).filter(ScheduledTaskRun.job_id == job.id).one()
            if job.status in ("succeeded", "failed") and run.status in ("succeeded", "failed"):
                db.expunge(job)
                db.expunge(run)
                return job, run
        time.sleep(0.1)
    raise AssertionError("webhook 触发的运行没跑完")


def _close_sessions() -> None:
    """上一次运行开的池会话随运行结束关掉;这里等它关完再跑下一次,免得撞租约。"""
    with SessionLocal() as db:
        db.execute(text("UPDATE browser_sessions SET status = 'closed'"))
        db.commit()


def _mate_edits(mate: TestClient, workflow: dict, profile_id: str) -> dict:
    changed = mate.patch(
        f"/api/workflows/{workflow['id']}",
        json={"graph": _graph(profile_id, session_name="改过"), "base_graph_hash": workflow["graph_hash"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == workflow["revision"] + 1
    return changed.json()


def test_a_mates_edit_cannot_borrow_the_owners_profile_until_the_owner_approves() -> None:
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])
    workflow, task = _hooked(owner, workspace["id"], profile_id)

    job, _run = _fire(owner, task)
    assert job.status == "succeeded", job.error  # 主人自己写的图,主人的任务:照旧
    _close_sessions()

    edited = _mate_edits(mate, workflow, profile_id)
    job, run = _fire(owner, task)
    assert job.status == "failed"
    assert job.error_key == "shareErr_notVouched_browserProfile", job.error
    assert job.created_by == _uid("tester"), "跑的人还是任务主人 —— 挡住它的是那一版的作者"
    attest = run.result["attest"]
    assert attest == {"workflow_id": workflow["id"], "workflow_name": "钩子", "revision": edited["revision"]}
    assert "认可这一版" in (run.error or "")
    _close_sessions()

    # 同事自己认可不算数:认可只对认可的人**自己用得了**的东西有用(他本来就是作者,这一下是空操作)。
    assert mate.post(f"/api/workflows/{workflow['id']}/revisions/{edited['revision']}/attest").status_code == 200
    job, _run = _fire(owner, task)
    assert job.error_key == "shareErr_notVouched_browserProfile"
    _close_sessions()

    approved = owner.post(f"/api/workflows/{workflow['id']}/revisions/{edited['revision']}/attest")
    assert approved.status_code == 200, approved.text
    assert approved.json()["attested_by"] == [_uid("tester")]
    assert approved.json()["created_by"] == _uid("mate")
    # 认可不改图、不增版。
    assert owner.get(f"/api/workflows/{workflow['id']}").json()["revision"] == edited["revision"]

    job, _run = _fire(owner, task)
    assert job.status == "succeeded", job.error


def test_sharing_the_profile_makes_the_edit_fine_without_approval() -> None:
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])
    workflow, task = _hooked(owner, workspace["id"], profile_id)
    owner.post(f"/api/shares/browser_profile/{profile_id}", json={"workspace_id": workspace["id"]})
    _mate_edits(mate, workflow, profile_id)
    job, _run = _fire(owner, task)
    assert job.status == "succeeded", job.error


def test_attest_answers_for_missing_revisions_and_lists_authors() -> None:
    owner, workspace, _mate = _team()
    workflow = owner.post("/api/workflows", json={"workspace_id": workspace["id"], "name": "W"}).json()
    assert owner.post(f"/api/workflows/{workflow['id']}/revisions/99/attest").status_code == 404
    rows = owner.get(f"/api/workflows/{workflow['id']}/revisions").json()
    assert rows[0]["created_by"] == _uid("tester")
    assert rows[0]["created_by_name"] == "tester"
    assert rows[0]["attested_by"] == []
    # 作者自己认可是空操作,不重复记。
    again = owner.post(f"/api/workflows/{workflow['id']}/revisions/1/attest").json()
    assert again["attested_by"] == []


def test_a_called_workflows_own_revision_counts_too() -> None:
    """call_workflow 调起的子流程是一条子 job:它自己那一版的担保人也要过,报错点名的是它。"""
    from app.domain.jobs import create_job, reset_parent_job, set_parent_job
    from app.domain.workflows.authority import current_authority
    from app.domain.workflows.revisions import current_workflow_revision

    owner, workspace, _mate = _team()
    profile_id = _profile(owner, workspace["id"])
    with SessionLocal() as db:
        parent = workflows.create_workflow(db, workspace_id=workspace["id"], name="父", created_by=_uid("tester"))
        child = workflows.create_workflow(db, workspace_id=workspace["id"], name="子", created_by=_uid("mate"))

        def pinned(workflow: Workflow) -> dict:
            revision = current_workflow_revision(db, workflow)
            return {"workflow_id": workflow.id, "workflow_revision_id": revision.id, "workflow_revision": revision.revision}

        outer = create_job(db, workspace_id=workspace["id"], kind="workflow", payload=pinned(parent), created_by=_uid("tester"))
        db.flush()
        token = set_parent_job(outer.id)
        try:
            inner = create_job(db, workspace_id=workspace["id"], kind="workflow", payload=pinned(child), created_by=_uid("tester"))
        finally:
            reset_parent_job(token)
        db.commit()
        assert inner.parent_job_id == outer.id
        inner_id = inner.id

    token = set_parent_job(inner_id)
    try:
        with SessionLocal() as db:
            authority = current_authority(db)
            assert authority.actor == _uid("tester")
            assert [voucher.workflow_name for voucher in authority.vouchers] == ["子", "父"]
            with pytest.raises(sharing.NotVouchedError) as refused:
                browser.usable_profile(db, workspace["id"], profile_id, actor=authority)
            assert refused.value.details["attest"]["workflow_name"] == "子"
    finally:
        reset_parent_job(token)


def test_host_files_follow_the_revision_author_too(tmp_path) -> None:
    """管理员跑、同事改过的那一版读本机路径:同样要管理员认可。"""
    from app.domain import host_files
    from app.domain.authority import Authority, Voucher

    _team()
    secret = tmp_path / "id_rsa"
    secret.write_text("k")
    voucher = Voucher(workflow_id="w", workflow_name="W", revision=3, users=frozenset({_uid("mate")}))
    with SessionLocal() as db:
        with pytest.raises(host_files.HostFileNotVouched) as refused:
            host_files.ensure_readable(db, str(secret), actor=Authority(_uid("tester"), (voucher,)))
        assert refused.value.key == "hostErr_notVouched"
        approved = Voucher(workflow_id="w", workflow_name="W", revision=3, users=frozenset({_uid("mate"), _uid("tester")}))
        host_files.ensure_readable(db, str(secret), actor=Authority(_uid("tester"), (approved,)))


# ---------------- 迁移:老修订补上作者 ----------------


def test_old_revisions_get_the_workflows_creator_as_author() -> None:
    from app.db.migrations import _backfill_workflow_revision_authors

    owner, workspace, mate = _team()
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": []}
    known = mate.post("/api/workflows", json={"workspace_id": workspace["id"], "name": "同事建的", "graph": graph}).json()
    changed = {"nodes": [{"id": "start", "type": "start", "config": {"params": {"v": 1}}}], "edges": []}
    owner.patch(f"/api/workflows/{known['id']}", json={"graph": changed, "base_graph_hash": known["graph_hash"]})
    unknown = owner.post("/api/workflows", json={"workspace_id": workspace["id"], "name": "没记作者", "graph": graph}).json()
    with engine.begin() as conn:
        # 老数据:第二版(和整条「没记作者」的)说不出是谁存的。
        conn.execute(text("UPDATE workflow_revisions SET created_by = NULL WHERE workflow_id = :id AND revision = 2"), {"id": known["id"]})
        conn.execute(text("UPDATE workflow_revisions SET created_by = NULL WHERE workflow_id = :id"), {"id": unknown["id"]})

    _backfill_workflow_revision_authors()

    with engine.begin() as conn:
        authors = dict(conn.execute(text(
            "SELECT workflow_id || ':' || revision, created_by FROM workflow_revisions"
        )).all())
    assert authors[f"{known['id']}:1"] == _uid("mate")
    assert authors[f"{known['id']}:2"] == _uid("mate"), "创建者 = 最早一版有记录的作者"
    assert authors[f"{unknown['id']}:1"] == _uid("tester"), "一版都没记录时是工作区 owner"

    _backfill_workflow_revision_authors()  # 再跑一次什么都不做
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM workflow_revisions WHERE created_by IS NULL")).scalar() == 0
