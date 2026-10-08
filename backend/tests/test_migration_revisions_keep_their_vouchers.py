"""迁移落下的修订沿用上一版的作者和担保人 —— 升级之后,用私有浏览器档案的流程照样跑得起来。

## 现场

1.8.1 的循环作用域迁移只改 `workflows.graph`,再由修订迁移把改动记成新的一版:那一版 `created_by` 为空、
不带认可。一次运行要用私有发布账号 / 浏览器档案 / 本机文件时,被执行那一版得有人担保(domain/authority),
于是被改写过的工作流升级之后一跑到那一步就报「这一版没人担保」,而用户什么都没改过。

修法两半:迁移改走 `_rewrite_workflow_graphs`(作者沿用上一版、认可照抄);已经升过 1.8.1 的库由
`migrate-migration-revisions-keep-their-vouchers` 给那些没作者的迁移修订补上。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import (
    _migrate_loop_scopes_are_not_outer_data_edges,
    _migrate_migration_revisions_keep_their_vouchers,
    _migrate_workflow_revisions,
)
from app.db.models import User, Workflow
from app.domain.workflows.revisions import current_workflow_revision, graph_digest, revision_vouchers
from tests.util import fresh_client, second_client, wait_status


def _uid(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _graph(profile_id: str, *, corrupted: bool) -> dict:
    """主人的浏览器档案 + 一个遍历循环。`corrupted`:循环的 output 被旧规范化接成了外层数据边。"""
    loop_config = {
        "items": "a",
        "body": {"nodes": [{"id": "t", "type": "template", "config": {"template": "体内"}}], "edges": []},
        "output": "" if corrupted else "{{t.text}}",
    }
    edges = [
        {"id": "e1", "source": "start", "target": "open"},
        {"id": "e2", "source": "open", "target": "each"},
    ]
    if corrupted:
        edges.append({"id": "d-t", "source": "t", "target": "each", "kind": "data",
                      "source_output": "text", "target_input": "output"})
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "open", "type": "browser_open",
             "config": {"session_mode": "pool", "profile_id": profile_id, "session_name": ""}},
            {"id": "t", "type": "template", "config": {"template": "外层"}},
            {"id": "each", "type": "loop_foreach", "config": loop_config, **({"inputs": ["output"]} if corrupted else {})},
        ],
        "edges": edges,
    }


def _owner_with_profile():
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    profile = owner.post("/api/browser/profiles", json={"workspace_id": workspace["id"], "name": "主人的浏览器"})
    assert profile.status_code == 200, profile.text
    return owner, workspace["id"], profile.json()["id"]


def _set_corrupted_like_1_8_0(workflow_id: str, graph: dict) -> None:
    """1.8.0 存下的样子:当前图和最新修订都是被改写过的那份。"""
    stored, digest = json.dumps(graph, ensure_ascii=False), graph_digest(graph)
    with engine.begin() as connection:
        connection.execute(text("UPDATE workflows SET graph = :g, graph_hash = :h WHERE id = :id"),
                           {"g": stored, "h": digest, "id": workflow_id})
        connection.execute(text("UPDATE workflow_revisions SET graph = :g, graph_hash = :h WHERE workflow_id = :id"),
                           {"g": stored, "h": digest, "id": workflow_id})


def _run(client, workflow_id: str) -> dict:
    started = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
    assert started.status_code == 200, started.text
    wait_status(client, started.json()["id"], timeout=15)
    return client.get(f"/api/jobs/{started.json()['id']}").json()


def _run_unattended(client, workflow_id: str) -> dict:
    """没人看着的那一种运行(到点的定时任务、webhook):不像点「运行」那样顺手认可当前版(ADR 0047 D6),
    所以「这一版没人担保」照样会停下来 —— 迁移修的正是这个。"""
    from app.domain.workflows.engine import start_workflow_job

    with SessionLocal() as db:
        job_id = start_workflow_job(db, db.get(Workflow, workflow_id), created_by=_uid("tester")).id
        db.commit()  # 测试是入口:任务在起它的那次事务提交之后才派发
    wait_status(client, job_id, timeout=15)
    return client.get(f"/api/jobs/{job_id}").json()


def _close_sessions() -> None:
    with SessionLocal() as db:
        db.execute(text("UPDATE browser_sessions SET status = 'closed'"))
        db.commit()


def test_循环作用域迁移落的新一版沿用作者_用主人档案的流程照样跑得起来() -> None:
    owner, ws, profile_id = _owner_with_profile()
    workflow_id = owner.post("/api/workflows", json={"workspace_id": ws, "name": "被改写过"}).json()["id"]
    _set_corrupted_like_1_8_0(workflow_id, _graph(profile_id, corrupted=True))

    _migrate_loop_scopes_are_not_outer_data_edges()

    with SessionLocal() as db:
        revision = current_workflow_revision(db, db.get(Workflow, workflow_id))
        assert revision.source == "migration" and revision.revision == 2
        assert revision.created_by == _uid("tester")
        each = next(node for node in revision.graph["nodes"] if node["id"] == "each")
        assert each["config"]["output"] == "{{t.text}}"
    job = _run(owner, workflow_id)
    assert job["status"] == "succeeded", job.get("error")
    assert job["result"]["context"]["each"]["results"] == ["体内"]


def test_已经升过的库_没作者的迁移修订补上上一版的作者和认可_连着几版也接得上() -> None:
    owner, ws, profile_id = _owner_with_profile()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    created = owner.post("/api/workflows", json={"workspace_id": ws, "name": "流程"}).json()
    # 同事改了一版、主人认可过:这一版的担保人是同事(作者)和主人(认可)。
    edited = mate.patch(f"/api/workflows/{created['id']}",
                        json={"graph": _graph(profile_id, corrupted=False), "base_graph_hash": created["graph_hash"]})
    assert edited.status_code == 200, edited.text
    assert owner.post(f"/api/workflows/{created['id']}/revisions/{edited.json()['revision']}/attest").status_code == 200

    # 1.8.1 的老路:改投影、由修订迁移补一版 —— 连着两次,两版都没有作者。
    for name in ("迁移改过一次", "迁移又改过一次"):
        graph = _graph(profile_id, corrupted=False)
        graph["nodes"][2]["name"] = name
        with engine.begin() as connection:
            connection.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                               {"g": json.dumps(graph, ensure_ascii=False), "id": created["id"]})
        _migrate_workflow_revisions()
    with SessionLocal() as db:
        stale = current_workflow_revision(db, db.get(Workflow, created["id"]))
        assert stale.revision == 4 and stale.created_by is None and not revision_vouchers(db, stale)
    _close_sessions()
    failed = _run_unattended(owner, created["id"])
    assert failed["status"] == "failed" and "认可这一版" in failed["error"], failed
    _close_sessions()

    _migrate_migration_revisions_keep_their_vouchers()
    _migrate_migration_revisions_keep_their_vouchers()  # 重跑:没有可补的,不重复记认可

    with SessionLocal() as db:
        workflow = db.get(Workflow, created["id"])
        for number in (3, 4):
            from app.domain.workflows.revisions import get_workflow_revision

            revision = get_workflow_revision(db, workflow.id, number)
            assert revision.created_by == _uid("mate")
            assert revision_vouchers(db, revision) == {_uid("mate"), _uid("tester")}
    job = _run(owner, created["id"])
    assert job["status"] == "succeeded", job.get("error")
