"""私有的发布账号与浏览器池档案,只有主人和被共享到的人能**用** —— 在用的那一刻查,每个入口都算数。

此前 `sharing.may_use` 写好了却只挡住了列表:工作流发布节点、`browser_open` 池模式、发布接口、
智能体的确认卡、定时任务与 webhook 触发的运行,全都只查「是不是这个工作区的人」。同事猜到 id、
或在工作流里填上别人的账号 id,就能拿别人的平台登录态发帖、在别人已登录的浏览器里取 cookie。

修法是**一道闸,放在用的那一刻**:`publish.start_publish` 与 `browser.open_session` /
`browser.attach_session` / `browser.usable_profile` 都**必须**收一个 `actor`(谁在用,用户 id),
没有默认值 —— 漏传是 TypeError,传 None 是被拒。这一条钉的是代码形状:没有第二条不带 actor
的路通往别人的身份。下面的行为测试逐个入口验一遍。

谁是 actor:路由是当前用户;工作流是这次运行的操作人(`jobs.current_actor`),定时任务与
webhook 触发的运行记在**任务主人**头上(scheduler.operations._open_run);确认卡是批准它的人。
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

from app.core.db import SessionLocal
from app.db.models import BrowserSession, Job, User
from app.domain import browser, sharing
from app.domain.publish import start_publish
from tests.util import fresh_client, make_video_asset, second_client

#: 用的那一刻。每一个都必须有一个**必填**的关键字参数 `actor`。
SEAMS = {
    "start_publish": start_publish,
    "open_session": browser.open_session,
    "attach_session": browser.attach_session,
    "usable_profile": browser.usable_profile,
}


# ---------------- 棘轮:形状 ----------------


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_the_seam_requires_an_actor(name: str) -> None:
    """`actor` 是必填的关键字参数 —— 给个默认值,就等于让漏传的那个入口静默放行。"""
    param = inspect.signature(SEAMS[name]).parameters.get("actor")
    assert param is not None, f"{name} 没有 actor 参数"
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} 的 actor 该是关键字参数"
    assert param.default is inspect.Parameter.empty, f"{name} 的 actor 有默认值 —— 漏传的入口会静默放行"


def _seam_calls() -> list[tuple[str, int, str, ast.Call]]:
    found: list[tuple[str, int, str, ast.Call]] = []
    paths = [*sorted(pathlib.Path("app").rglob("*.py")), pathlib.Path("mcp_server.py")]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name in SEAMS:
                found.append((str(path), node.lineno, name, node))
    return found


def test_every_caller_names_a_real_actor() -> None:
    """每个调用点都**显式**写出 `actor=`,而且不是字面量 None。

    None 在闸里会被拒,所以写 None 的入口不是越权,是一条永远用不了私有身份的死路 —— 它说明那个
    入口没想清楚「这次是替谁用」。要的是想清楚,不是躲过检查。
    """
    calls = _seam_calls()
    assert calls, "一个调用点都没扫到 —— 扫描本身坏了"
    bad: list[str] = []
    for path, line, name, call in calls:
        actor = next((kw for kw in call.keywords if kw.arg == "actor"), None)
        if actor is None:
            bad.append(f"{path}:{line} {name}(…) 没传 actor")
        elif isinstance(actor.value, ast.Constant) and actor.value.value is None:
            bad.append(f"{path}:{line} {name}(…, actor=None)")
    assert not bad, "这些入口没说清是谁在用:\n  " + "\n  ".join(bad)


def test_no_actor_means_no_use() -> None:
    """说不出是谁在用 —— 一律不能用。没有「不知道是谁就放行」这一档。"""

    class _Row:
        id = "r1"
        owner_user_id = None
        workspace_id = "w1"

    with SessionLocal() as db:
        assert sharing.may_use(db, "publish_account", _Row(), None) is False
        assert sharing.may_use(db, "publish_account", _Row(), "") is False


# ---------------- 行为:准备 ----------------


def _team() -> tuple[TestClient, dict, TestClient]:
    """owner(tester)建工作区,mate 以 editor 加入 —— 同一个工作区里的两个人。"""
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


def _account(client: TestClient, workspace_id: str) -> dict:
    """建一个发布账号(连带它的池档案)。默认私有。"""
    made = client.post(
        "/api/publish/accounts",
        json={"workspace_id": workspace_id, "platform": "bilibili", "name": "主人的 B 站", "config": {}},
    )
    assert made.status_code == 200, made.text
    return made.json()


def _profile(client: TestClient, workspace_id: str) -> str:
    made = client.post("/api/browser/profiles", json={"workspace_id": workspace_id, "name": "主人的浏览器"})
    assert made.status_code == 200, made.text
    return made.json()["id"]


def _share(client: TestClient, kind: str, resource_id: str, workspace_id: str) -> None:
    shared = client.post(f"/api/shares/{kind}/{resource_id}", json={"workspace_id": workspace_id})
    assert shared.status_code == 200, shared.text


def _publish(client: TestClient, workspace_id: str, account_id: str, asset_id: str):
    return client.post(
        "/api/publish/tasks",
        json={"workspace_id": workspace_id, "account_id": account_id, "asset_id": asset_id, "title": "t"},
    )


# ---------------- 发布接口 ----------------


def test_a_mate_cannot_publish_with_a_private_account() -> None:
    owner, workspace, mate = _team()
    account = _account(owner, workspace["id"])
    asset = make_video_asset(owner, workspace["id"])

    refused = _publish(mate, workspace["id"], account["id"], asset["id"])
    assert refused.status_code == 403, refused.text
    assert "共享" in refused.json()["detail"], "拒绝要说清是归属的问题,不是一句笼统的 403"

    en = mate.post(
        "/api/publish/tasks",
        json={"workspace_id": workspace["id"], "account_id": account["id"], "asset_id": asset["id"]},
        headers={"Accept-Language": "en"},
    )
    assert "hasn't been shared" in en.json()["detail"]


def test_the_owner_and_the_shared_can_publish() -> None:
    owner, workspace, mate = _team()
    account = _account(owner, workspace["id"])
    asset = make_video_asset(owner, workspace["id"])

    assert _publish(owner, workspace["id"], account["id"], asset["id"]).status_code == 200

    _share(owner, "publish_account", account["id"], workspace["id"])
    assert _publish(mate, workspace["id"], account["id"], asset["id"]).status_code == 200


def test_withdrawing_the_share_stops_new_publishes() -> None:
    owner, workspace, mate = _team()
    account = _account(owner, workspace["id"])
    asset = make_video_asset(owner, workspace["id"])
    _share(owner, "publish_account", account["id"], workspace["id"])
    owner.request("DELETE", f"/api/shares/publish_account/{account['id']}", json={"workspace_id": workspace["id"]})

    assert _publish(mate, workspace["id"], account["id"], asset["id"]).status_code == 403


# ---------------- 工作流发布节点 ----------------


def _run_node(node_type: str, workspace_id: str, actor_id: str | None, config: dict) -> dict:
    """在一次「替 actor 跑」的工作流运行里执行一个节点(和引擎给执行器的上下文一样)。"""
    from app.db.models import Workflow
    from app.domain.jobs import create_job, reset_parent_job, set_parent_job
    from app.domain.workflows import create_workflow
    from app.domain.workflows.executors import get_executor

    with SessionLocal() as db:
        workflow_id = create_workflow(db, workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []}).id
        run = create_job(db, workspace_id=workspace_id, kind="workflow", payload={}, created_by=actor_id)
        run.status = "running"
        db.commit()
        run_id = run.id
    token = set_parent_job(run_id)
    try:
        with SessionLocal() as db:
            return get_executor(node_type)(db, db.get(Workflow, workflow_id), config)
    finally:
        reset_parent_job(token)


def test_the_publish_node_runs_as_the_runs_actor(monkeypatch) -> None:
    from app.domain.workflows.executors import subjobs

    # 发布任务要等桌面端执行器 —— 这里只关心任务建不建得出来。
    monkeypatch.setattr(subjobs, "wait_for_job", lambda job_id, release=None: type("J", (), {"result": {}})())
    owner, workspace, _mate = _team()
    account = _account(owner, workspace["id"])
    asset = make_video_asset(owner, workspace["id"])
    config = {"account_id": account["id"], "asset_id": asset["id"], "title": "t"}

    with pytest.raises(sharing.NotUsableError) as refused:
        _run_node("publish", workspace["id"], _uid("mate"), config)
    assert refused.value.key == "shareErr_notUsable_publishAccount"

    # 说不出替谁跑 —— 同样不能用。
    with pytest.raises(sharing.NotUsableError):
        _run_node("publish", workspace["id"], None, config)

    _run_node("publish", workspace["id"], _uid("tester"), config)  # 主人自己的运行
    owner.post(f"/api/shares/publish_account/{account['id']}", json={"workspace_id": workspace["id"]})
    _run_node("publish", workspace["id"], _uid("mate"), config)  # 共享之后同事也能用


# ---------------- 智能体确认卡 ----------------


def _card(client: TestClient, workspace_id: str, tool: str, payload: dict) -> dict:
    made = client.post("/api/confirmations", json={"workspace_id": workspace_id, "tool": tool, "payload": payload})
    assert made.status_code == 200, made.text
    return client.post(f"/api/confirmations/{made.json()['id']}/approve").json()


def test_the_publish_card_uses_the_approvers_authority() -> None:
    owner, workspace, mate = _team()
    account = _account(owner, workspace["id"])
    asset = make_video_asset(owner, workspace["id"])
    payload = {"account_id": account["id"], "asset_id": asset["id"], "title": "t"}

    denied = _card(mate, workspace["id"], "publish_asset", payload)
    assert denied["status"] == "failed", denied
    assert "共享" in (denied.get("error") or "")

    assert _card(owner, workspace["id"], "publish_asset", payload)["status"] == "executed"


def test_the_pool_card_uses_the_approvers_authority() -> None:
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])

    denied = _card(mate, workspace["id"], "browser_pool_open", {"profile_id": profile_id, "url": ""})
    assert denied["status"] == "failed", denied

    _share(owner, "browser_profile", profile_id, workspace["id"])
    allowed = _card(mate, workspace["id"], "browser_pool_open", {"profile_id": profile_id, "url": ""})
    assert allowed["status"] == "executed", allowed


# ---------------- browser_open 池模式与接着用一个会话 ----------------


def test_a_mate_cannot_open_a_private_pool_profile() -> None:
    from app.domain.workflows import WorkflowDomainError

    owner, workspace, _mate = _team()
    profile_id = _profile(owner, workspace["id"])
    config = {"session_mode": "pool", "profile_id": profile_id}

    with pytest.raises(WorkflowDomainError) as refused:
        _run_node("browser_open", workspace["id"], _uid("mate"), config)
    assert refused.value.key == "shareErr_notUsable_browserProfile"
    with SessionLocal() as db:
        assert db.query(BrowserSession).filter(BrowserSession.profile_id == profile_id).count() == 0

    opened = _run_node("browser_open", workspace["id"], _uid("tester"), config)
    assert opened["session"]


def test_a_shared_pool_profile_opens_for_the_mate() -> None:
    owner, workspace, _mate = _team()
    profile_id = _profile(owner, workspace["id"])
    _share(owner, "browser_profile", profile_id, workspace["id"])

    opened = _run_node("browser_open", workspace["id"], _uid("mate"), {"session_mode": "pool", "profile_id": profile_id})
    with SessionLocal() as db:
        assert db.get(BrowserSession, opened["session"]).profile_id == profile_id


def test_a_session_id_is_not_a_key_to_someone_elses_browser() -> None:
    """主人开着自己的池档案会话;同事拿到会话 id,也不能在里面跑动作。"""
    from app.domain.workflows import WorkflowDomainError

    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])
    with SessionLocal() as db:
        session_id = browser.open_session(
            db, workspace_id=workspace["id"], profile_id=profile_id, owner_kind="manual", actor=_uid("tester")
        ).id

    acted = mate.post(
        "/api/agent-browser/act",
        json={"workspace_id": workspace["id"], "session_id": session_id, "action": "extract", "args": {}},
    )
    assert acted.status_code == 403, acted.text
    closed = mate.post("/api/agent-browser/close", json={"workspace_id": workspace["id"], "session_id": session_id})
    assert closed.status_code == 403, closed.text

    with pytest.raises(WorkflowDomainError) as refused:
        _run_node("browser_navigate", workspace["id"], _uid("mate"), {"session": session_id, "url": "https://example.com"})
    assert refused.value.key == "shareErr_notUsable_browserProfile"


# ---------------- 定时任务 / webhook:记在任务主人头上 ----------------


def _webhook_run(client: TestClient, workspace_id: str, profile_id: str) -> Job:
    """这个人挂一条 webhook 任务,图里用 profile_id 开池会话;触发它,等到终态。"""
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "open", "type": "browser_open", "config": {"session_mode": "pool", "profile_id": profile_id}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "open"}],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": workspace_id, "name": "钩子", "graph": graph})
    assert workflow.status_code == 200, workflow.text
    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": workspace_id, "name": "钩子任务", "kind": "workflow", "trigger_type": "webhook",
            "schedule": {}, "payload": {"workflow_id": workflow.json()["id"], "params": {}},
        },
    ).json()
    fired = client.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret={task['payload']['webhook_secret']}")
    assert fired.status_code == 200, fired.text
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.get(Job, fired.json()["job_id"])
            if job.status in ("succeeded", "failed"):
                db.expunge(job)
                return job
        time.sleep(0.1)
    raise AssertionError("webhook 触发的运行没跑完")


def test_a_webhook_run_acts_as_the_task_owner() -> None:
    """webhook 没有登录态 —— 这次运行替**任务主人**用东西,主人自己的私有档案借得到,
    同事挂的任务借不到它。"""
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])

    mine = _webhook_run(owner, workspace["id"], profile_id)
    assert mine.status == "succeeded", mine.error
    assert mine.created_by == _uid("tester")

    theirs = _webhook_run(mate, workspace["id"], profile_id)
    assert theirs.status == "failed"
    assert theirs.created_by == _uid("mate")
    assert theirs.error_key == "shareErr_notUsable_browserProfile", theirs.error


# ---------------- 从链接导入借 cookie ----------------


def test_a_mate_cannot_borrow_a_private_profiles_cookies_for_url_import() -> None:
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])
    body = {
        "workspace_id": workspace["id"], "items": [{"url": "https://example.com/v", "title": "v"}],
        "kind": "video", "profile_id": profile_id,
    }
    refused = mate.post("/api/assets/import-url", json=body)
    assert refused.status_code == 403, refused.text
    probed = mate.post(
        "/api/assets/probe-url",
        json={"workspace_id": workspace["id"], "url": "https://example.com/v", "profile_id": profile_id},
    )
    assert probed.status_code == 403, probed.text


# ---------------- 下拉:给的就是用得上的 ----------------


def _options(client: TestClient, source: str, workspace_id: str) -> list[str]:
    got = client.get(f"/api/workflows/field-options?source={source}&workspace_id={workspace_id}")
    assert got.status_code == 200, got.text
    return [row["value"] for row in got.json()]


def test_pickers_only_offer_what_you_may_use() -> None:
    """工作流字段的下拉和用的那一刻是同一个判据:列出来的,选了就用得上。"""
    from app.db.models import PublishAccount

    owner, workspace, mate = _team()
    account = _account(owner, workspace["id"])
    profile_id = _profile(owner, workspace["id"])
    with SessionLocal() as db:
        account_profile = db.get(PublishAccount, account["id"]).profile_id

    assert account["id"] in _options(owner, "publish_accounts", workspace["id"])
    assert profile_id in _options(owner, "browser_profiles", workspace["id"])
    assert account["id"] not in _options(mate, "publish_accounts", workspace["id"])
    assert profile_id not in _options(mate, "browser_profiles", workspace["id"])
    assert account_profile not in _options(mate, "browser_profiles", workspace["id"])

    _share(owner, "publish_account", account["id"], workspace["id"])
    _share(owner, "browser_profile", profile_id, workspace["id"])
    assert account["id"] in _options(mate, "publish_accounts", workspace["id"])
    assert profile_id in _options(mate, "browser_profiles", workspace["id"])
    # 共享账号连带它的档案(同一个身份的两半,见 sharing._companions)。
    assert account_profile in _options(mate, "browser_profiles", workspace["id"])


def test_the_browser_open_profile_field_is_a_picker() -> None:
    """池档案这一格从下拉里挑,不再要人去浏览器池把 id 抄过来。"""
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.field_options import SOURCES

    source = NODE_TYPES["browser_open"]["config"]["profile_id"].get("options_from")
    assert source in SOURCES
