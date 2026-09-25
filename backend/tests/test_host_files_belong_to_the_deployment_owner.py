"""这台电脑上的文件是**部署主人的** —— 读一个用户给出的本机路径,只在一处判,每个入口都算数。

此前工作流 `browser_upload` 节点的 `file_path` 收后端机器上的任意路径,智能体浏览器的 upload 动作
把 args 原样交给执行器,「本机执行代码」谁批准都跑。单机用时那台电脑就是用户自己的,没问题;同事经
团队部署或远程访问进来之后,填一个 `~/.ssh/id_rsa`,主人的私钥就被塞进了任意网页。

修法是**一道闸**:`domain/host_files`。`ensure_readable(path, actor=…)` / `ensure_whole_machine(actor=…)`
的 `actor` 必填、没有默认值;放行得到的是一个只有那个模块造得出的 `HostFile`,浏览器上传只收它。
规则:部署管理员整台机器都行;其他人只有素材库里的文件,或管理员共享给成员的本机文件夹里的路径。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import inspect
import os
import pathlib

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import User
from app.domain import browser, host_files
from tests.util import pinned, fresh_client, make_video_asset, second_client

#: 读本机的那一刻。每一个都必须有一个**必填**的关键字参数 `actor`。
SEAMS = {
    "ensure_readable": host_files.ensure_readable,
    "ensure_whole_machine": host_files.ensure_whole_machine,
}

#: 收用户给出的本机路径(或在本机跑代码)的入口 —— 每一个的函数体里都必须过 host_files。
#: 新加一个这样的入口,加进这里;它会先在这里红,而不是先在别人的电脑上漏。
ENTRY_POINTS = {
    ("app/domain/workflows/executors/browser.py", "browser_upload"),
    ("app/api/routes/agent_browser.py", "_upload_source"),
    ("app/api/routes/assets.py", "import_local_asset"),
    ("app/domain/agent/confirmable/external.py", "_execute_run_host_code"),
    ("app/domain/agent/confirmable/blender.py", "_execute_blender_execute"),
}


# ---------------- 棘轮:形状 ----------------


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_the_seam_requires_an_actor(name: str) -> None:
    param = inspect.signature(SEAMS[name]).parameters.get("actor")
    assert param is not None, f"{name} 没有 actor 参数"
    assert param.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} 的 actor 该是关键字参数"
    assert param.default is inspect.Parameter.empty, f"{name} 的 actor 有默认值 —— 漏传的入口会静默放行"


def _trees() -> list[tuple[pathlib.Path, ast.AST]]:
    paths = [*sorted(pathlib.Path("app").rglob("*.py")), pathlib.Path("mcp_server.py")]
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in paths]


def _name(func: ast.expr) -> str:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def test_every_caller_names_a_real_actor() -> None:
    calls = [
        (path, node) for path, tree in _trees() for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _name(node.func) in SEAMS
    ]
    assert calls, "一个调用点都没扫到 —— 扫描本身坏了"
    bad = []
    for path, call in calls:
        actor = next((kw for kw in call.keywords if kw.arg == "actor"), None)
        if actor is None:
            bad.append(f"{path}:{call.lineno} 没传 actor")
        elif isinstance(actor.value, ast.Constant) and actor.value.value is None:
            bad.append(f"{path}:{call.lineno} actor=None")
    assert not bad, "这些入口没说清是谁在读本机:\n  " + "\n  ".join(bad)


def test_only_host_files_makes_a_host_file() -> None:
    """`HostFile` 是「判过了」的凭证 —— 别处能造,闸就形同虚设。"""
    makers = [
        f"{path}:{node.lineno}" for path, tree in _trees() for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _name(node.func) == "HostFile" and path.as_posix() != "app/domain/host_files.py"
    ]
    assert not makers, "这些地方自己造了 HostFile,绕过了 host_files:\n  " + "\n  ".join(makers)


@pytest.mark.parametrize(("path", "function"), sorted(ENTRY_POINTS))
def test_every_entry_point_goes_through_the_seam(path: str, function: str) -> None:
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    body = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == function), None
    )
    assert body is not None, f"{path} 里没有 {function} —— 入口改名了,把清单跟上"
    used = {
        _name(node.func) for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "host_files"
    }
    assert used & {"ensure_readable", "asset_file", "ensure_whole_machine"}, f"{path}:{function} 没过 host_files"


def test_the_browser_only_uploads_a_host_file() -> None:
    """`run_action` 不接 upload,导航只认 http(s) —— 两条都是读本机文件的门。"""
    with pytest.raises(browser.BrowserDomainError) as upload:
        browser.run_action("nope", "upload", {"path": "/etc/hosts"})
    assert upload.value.key == "browserErr_uploadNeedsHostFile"
    with pytest.raises(browser.BrowserDomainError) as navigate:
        browser.run_action("nope", "navigate", {"url": "file:///etc/hosts"})
    assert navigate.value.key == "browserErr_navigateScheme"
    with pytest.raises(browser.BrowserDomainError):
        browser.upload_file("nope", "/etc/hosts")  # type: ignore[arg-type]


def test_no_actor_reads_nothing(tmp_path) -> None:
    secret = tmp_path / "id_rsa"
    secret.write_text("k")
    with SessionLocal() as db:
        assert host_files.may_read(db, secret, actor=None) is False
        assert host_files.may_read(db, secret, actor="") is False


# ---------------- 行为:准备 ----------------


def _team():
    """tester 是引导账号(部署管理员);mate 是同一工作区里的 editor,不是管理员。"""
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


def _secret(tmp_path: pathlib.Path) -> pathlib.Path:
    home = tmp_path / "home" / ".ssh"
    home.mkdir(parents=True)
    key = home / "id_rsa"
    key.write_text("-----BEGIN PRIVATE KEY-----")
    return key


# ---------------- 共享文件夹:只有管理员能改 ----------------


def test_only_an_admin_sets_the_shared_folders(tmp_path) -> None:
    owner, _workspace, mate = _team()
    shared = tmp_path / "shared"
    shared.mkdir()

    refused = mate.put("/api/admin/shared-host-folders", json={"folders": [str(shared)]})
    assert refused.status_code == 403, refused.text

    saved = owner.put("/api/admin/shared-host-folders", json={"folders": [str(shared), str(shared / ".." / "shared")]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["folders"] == [os.path.realpath(shared)], "存真实路径,并去重"
    # 清单本来就是给成员用的:被挡下时他得知道该把文件放哪儿。
    assert mate.get("/api/admin/shared-host-folders").json()["folders"] == [os.path.realpath(shared)]


def test_the_shared_folders_must_be_real_folders(tmp_path) -> None:
    owner, _workspace, _mate = _team()
    for bad, key in (("relative/dir", "绝对路径"), (str(tmp_path / "missing"), "没有这个文件夹"), ("/", "根目录")):
        res = owner.put("/api/admin/shared-host-folders", json={"folders": [bad]})
        assert res.status_code == 422, bad
        assert key in res.json()["detail"]
    en = owner.put("/api/admin/shared-host-folders", json={"folders": ["/"]}, headers={"Accept-Language": "en"})
    assert "root directory" in en.json()["detail"]


# ---------------- 判据 ----------------


def test_admin_reads_anything_members_only_the_shared_folders(tmp_path) -> None:
    owner, _workspace, _mate = _team()
    secret = _secret(tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    inside = shared / "clip.mp4"
    inside.write_bytes(b"x")
    # 共享文件夹里放一个指向私钥的软链接,和一个 `..` 走出去的路径 —— 都不能借道。
    (shared / "sneaky.mp4").symlink_to(secret)
    owner.put("/api/admin/shared-host-folders", json={"folders": [str(shared)]})

    with SessionLocal() as db:
        admin, mate = _uid("tester"), _uid("mate")
        assert host_files.ensure_readable(db, str(secret), actor=admin).path == pathlib.Path(os.path.realpath(secret))
        assert host_files.ensure_readable(db, str(inside), actor=mate).path == pathlib.Path(os.path.realpath(inside))
        for sneaky in (secret, shared / "sneaky.mp4", shared / ".." / "home" / ".ssh" / "id_rsa"):
            with pytest.raises(host_files.HostFileNotAllowed) as refused:
                host_files.ensure_readable(db, str(sneaky), actor=mate)
            assert refused.value.key == "hostErr_notReadable"
        # 没权限的人探不出别人机器上有没有这个文件:不存在也是 403,不是 422。
        with pytest.raises(host_files.HostFileNotAllowed):
            host_files.ensure_readable(db, str(tmp_path / "nothing-here"), actor=mate)
        with pytest.raises(host_files.HostFileNotAllowed):
            host_files.ensure_readable(db, str(inside), actor=None)


def test_code_on_this_machine_needs_an_admin() -> None:
    _team()
    with SessionLocal() as db:
        host_files.ensure_whole_machine(db, actor=_uid("tester"))
        with pytest.raises(host_files.HostFileNotAllowed) as refused:
            host_files.ensure_whole_machine(db, actor=_uid("mate"))
        assert refused.value.key == "hostErr_codeNeedsAdmin"
        with pytest.raises(host_files.HostFileNotAllowed):
            host_files.ensure_whole_machine(db, actor=None)


# ---------------- 入口:工作流上传节点 ----------------


def _run_upload(workspace_id: str, actor_id: str | None, config: dict, monkeypatch) -> list:
    """在一次「替 actor 跑」的工作流运行里执行 browser_upload;真正交给执行器的那一步记下来。"""
    from app.db.models import Workflow
    from app.domain.jobs import create_job, reset_parent_job, set_parent_job
    from app.domain.workflows import create_workflow
    from app.domain.workflows.executors import get_executor

    uploaded: list = []
    monkeypatch.setattr(browser, "upload_file", lambda sid, file, **kw: uploaded.append(file) or {})
    with SessionLocal() as db:
        session_id = browser.open_session(db, workspace_id=workspace_id, owner_kind="manual", actor=actor_id).id
        workflow = create_workflow(
            db, workspace_id=workspace_id, name="W", graph={"nodes": [], "edges": []}, created_by=actor_id
        )
        workflow_id = workflow.id
        run = create_job(db, workspace_id=workspace_id, kind="workflow", payload=pinned(db, workflow), created_by=actor_id)
        run.status = "running"
        db.commit()
        run_id = run.id
    token = set_parent_job(run_id)
    try:
        with SessionLocal() as db:
            get_executor("browser_upload")(db, db.get(Workflow, workflow_id), {"session": session_id, **config})
    finally:
        reset_parent_job(token)
    return uploaded


def test_the_upload_node_reads_host_paths_only_for_the_admin(tmp_path, monkeypatch) -> None:
    from app.domain.workflows import WorkflowDomainError

    _owner, workspace, _mate = _team()
    secret = _secret(tmp_path)

    with pytest.raises(WorkflowDomainError) as refused:
        _run_upload(workspace["id"], _uid("mate"), {"file_path": str(secret)}, monkeypatch)
    assert refused.value.key == "hostErr_notReadable"

    uploaded = _run_upload(workspace["id"], _uid("tester"), {"file_path": str(secret)}, monkeypatch)
    assert [str(one) for one in uploaded] == [os.path.realpath(secret)]


def test_the_upload_node_still_takes_library_assets_from_anyone(tmp_path, monkeypatch) -> None:
    owner, workspace, _mate = _team()
    asset = make_video_asset(owner, workspace["id"])
    uploaded = _run_upload(workspace["id"], _uid("mate"), {"asset_id": asset["id"]}, monkeypatch)
    assert len(uploaded) == 1 and str(uploaded[0]).startswith(str(settings.data_dir))


# ---------------- 入口:智能体浏览器的 upload 动作 ----------------


def test_the_agent_upload_action_goes_through_the_seam(tmp_path, monkeypatch) -> None:
    owner, workspace, mate = _team()
    secret = _secret(tmp_path)
    asset = make_video_asset(owner, workspace["id"])
    uploaded: list = []
    monkeypatch.setattr(browser, "upload_file", lambda sid, file, **kw: uploaded.append(file) or {})
    with SessionLocal() as db:
        session_id = browser.open_session(db, workspace_id=workspace["id"], owner_kind="manual", actor=_uid("mate")).id

    def act(client, args):
        return client.post(
            "/api/agent-browser/act",
            json={"workspace_id": workspace["id"], "session_id": session_id, "action": "upload", "args": args},
        )

    refused = act(mate, {"selector": "input", "path": str(secret)})
    assert refused.status_code == 403, refused.text
    assert "管理员" in refused.json()["detail"]
    assert uploaded == []

    assert act(mate, {"selector": "input", "asset_id": asset["id"]}).status_code == 200
    assert act(owner, {"selector": "input", "path": str(secret)}).status_code == 200
    assert len(uploaded) == 2


# ---------------- 入口:按本机路径导入素材 ----------------


def test_local_import_is_the_admins_own_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    owner, workspace, mate = _team()
    clip = tmp_path / "private.mp4"
    clip.write_bytes(b"fake-video-bytes")

    refused = mate.post("/api/assets/import-local", json={"workspace_id": workspace["id"], "path": str(clip)})
    assert refused.status_code == 403, refused.text

    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "ok.mp4").write_bytes(b"fake-video-bytes")
    owner.put("/api/admin/shared-host-folders", json={"folders": [str(shared)]})
    allowed = mate.post(
        "/api/assets/import-local", json={"workspace_id": workspace["id"], "path": str(shared / "ok.mp4")}
    )
    assert allowed.status_code == 200, allowed.text


# ---------------- 入口:本机执行代码的确认卡 ----------------


def test_host_code_cards_need_an_admin_approver(monkeypatch) -> None:
    from app.domain.agent.confirmable.registry import tool_spec
    from app.domain.agent.errors import ConfirmationError

    monkeypatch.setattr(settings, "local_desktop", True)
    _team()

    class _Card:
        payload = {"code": "output = 1", "inputs": {}}
        workspace_id = "w"

    with SessionLocal() as db:
        with pytest.raises(ConfirmationError) as refused:
            tool_spec("run_host_code").execute(db, _Card(), _uid("mate"))
        assert refused.value.key == "hostErr_codeNeedsAdmin"
        with pytest.raises(ConfirmationError) as blender:
            tool_spec("blender_execute").execute(db, _Card(), _uid("mate"))
        assert blender.value.key == "hostErr_codeNeedsAdmin"
