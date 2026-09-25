"""私有的发布账号与浏览器池档案,**管**只认主人 —— 共享出去是借给人用,不是交给人管。

此前改名、停用 / 启用、改代理、复检、删除只查工作区角色:同事看不到别人的私有账号,可猜到 id 就能
把它停掉、删掉。共享进工作区的那些更是摆在列表里。§3.6 管的是「用」,这里管的是「管」。

修法是一道闸:`sharing.ensure_manageable(…, actor=…)`,只认 `owner_user_id == actor`(工作区 admin 也
不行,和 routes/shares 同一条)。管的动作收进领域函数(`publish.update_account` / `recheck_account` /
`delete_account`、`browser.update_profile` / `delete_profile`),`actor` 必填;路由回 403。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import inspect
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import BrowserProfile, PublishAccount
from app.domain import browser, publish, sharing
from tests.util import fresh_client, second_client

SEAMS = {
    "ensure_manageable": sharing.ensure_manageable,
    "update_account": publish.update_account,
    "recheck_account": publish.recheck_account,
    "delete_account": publish.delete_account,
    "update_profile": browser.update_profile,
    "delete_profile": browser.delete_profile,
}

#: 管私有身份的路由所在的文件,以及其中**只是在用**、不算管的那几条(路径)。
ROUTE_FILES = ("app/api/routes/publish.py", "app/api/routes/browser_profiles.py")
USE_NOT_MANAGE = {"/browser/profiles/{profile_id}/opened"}


#: 这几个名字只在这些模块上才是闸(`members.delete_account` 是删用户账号,另一回事)。
_OWNERS = {"sharing", "publish", "browser", "browser_domain"}


def _name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        owner = func.value.id if isinstance(func.value, ast.Name) else ""
        return func.attr if owner in _OWNERS or func.attr not in SEAMS else ""
    return ""


# ---------------- 棘轮:形状 ----------------


@pytest.mark.parametrize("name", sorted(SEAMS))
def test_managing_requires_an_actor(name: str) -> None:
    param = inspect.signature(SEAMS[name]).parameters.get("actor")
    assert param is not None and param.kind is inspect.Parameter.KEYWORD_ONLY, name
    assert param.default is inspect.Parameter.empty, f"{name} 的 actor 有默认值 —— 漏传的入口会静默放行"


def test_every_caller_names_a_real_actor() -> None:
    paths = [*sorted(pathlib.Path("app").rglob("*.py")), pathlib.Path("mcp_server.py")]
    bad, seen = [], 0
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _name(node.func) in SEAMS:
                seen += 1
                actor = next((kw for kw in node.keywords if kw.arg == "actor"), None)
                if actor is None or (isinstance(actor.value, ast.Constant) and actor.value.value is None):
                    bad.append(f"{path}:{node.lineno}")
    assert seen, "一个调用点都没扫到 —— 扫描本身坏了"
    assert not bad, "这些地方管私有身份没说清是谁:\n  " + "\n  ".join(bad)


def test_every_managing_route_goes_through_the_seam() -> None:
    """改 / 删一个具体账号或档案的路由(带 {account_id} / {profile_id} 的写入)都得经过上面那几个领域函数。"""
    checked, bad = 0, []
    for file in ROUTE_FILES:
        for fn in ast.walk(ast.parse(pathlib.Path(file).read_text(encoding="utf-8"))):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for deco in fn.decorator_list:
                if not (isinstance(deco, ast.Call) and _name(deco.func) in ("patch", "post", "put", "delete")):
                    continue
                path = deco.args[0].value if deco.args and isinstance(deco.args[0], ast.Constant) else ""
                if not ("{account_id}" in path or "{profile_id}" in path) or path in USE_NOT_MANAGE:
                    continue
                checked += 1
                calls = {_name(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
                if not calls & set(SEAMS):
                    bad.append(f"{file}:{fn.name} {path}")
    assert checked >= 5, "扫到的管理路由太少 —— 扫描本身坏了"
    assert not bad, "这些路由改了私有身份却没过 ensure_manageable:\n  " + "\n  ".join(bad)


# ---------------- 行为 ----------------


def _team() -> tuple[TestClient, dict, TestClient]:
    """tester 建工作区;mate 以 **admin** 加入 —— 工作区 admin 也管不了别人的登录态。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "admin"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


def _account(client: TestClient, workspace_id: str) -> dict:
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


def _manage_account(client: TestClient, account_id: str) -> list[int]:
    return [
        client.patch(f"/api/publish/accounts/{account_id}", json={"name": "改掉"}).status_code,
        client.patch(f"/api/publish/accounts/{account_id}", json={"enabled": False}).status_code,
        client.patch(f"/api/publish/accounts/{account_id}", json={"proxy": "http://127.0.0.1:1"}).status_code,
        client.post(f"/api/publish/accounts/{account_id}/recheck").status_code,
        client.delete(f"/api/publish/accounts/{account_id}").status_code,
    ]


def _manage_profile(client: TestClient, profile_id: str) -> list[int]:
    return [
        client.patch(f"/api/browser/profiles/{profile_id}", json={"name": "改掉"}).status_code,
        client.patch(f"/api/browser/profiles/{profile_id}", json={"enabled": False}).status_code,
        client.patch(f"/api/browser/profiles/{profile_id}", json={"proxy": "http://127.0.0.1:1"}).status_code,
        client.delete(f"/api/browser/profiles/{profile_id}").status_code,
    ]


@pytest.mark.parametrize("shared", [False, True])
def test_a_mate_cannot_manage_someone_elses_account(shared: bool) -> None:
    owner, workspace, mate = _team()
    account = _account(owner, workspace["id"])
    if shared:
        owner.post(f"/api/shares/publish_account/{account['id']}", json={"workspace_id": workspace["id"]})

    assert _manage_account(mate, account["id"]) == [403] * 5
    with SessionLocal() as db:
        row = db.get(PublishAccount, account["id"])
        assert row is not None and row.name == "主人的 B 站" and row.enabled and not row.proxy

    refused = mate.delete(f"/api/publish/accounts/{account['id']}", headers={"Accept-Language": "en"})
    assert "only its owner" in refused.json()["detail"]
    assert "只有主人" in mate.delete(f"/api/publish/accounts/{account['id']}").json()["detail"]

    assert _manage_account(owner, account["id"]) == [200, 200, 200, 200, 204]


@pytest.mark.parametrize("shared", [False, True])
def test_a_mate_cannot_manage_someone_elses_profile(shared: bool) -> None:
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])
    if shared:
        owner.post(f"/api/shares/browser_profile/{profile_id}", json={"workspace_id": workspace["id"]})

    assert _manage_profile(mate, profile_id) == [403] * 4
    with SessionLocal() as db:
        row = db.get(BrowserProfile, profile_id)
        assert row is not None and row.name == "主人的浏览器" and row.enabled

    assert _manage_profile(owner, profile_id) == [200, 200, 200, 204]


def test_using_a_shared_profile_is_still_fine() -> None:
    """管收紧了,用没变:共享给他的档案,他照样能开、能记下停在哪一页。"""
    owner, workspace, mate = _team()
    profile_id = _profile(owner, workspace["id"])
    owner.post(f"/api/shares/browser_profile/{profile_id}", json={"workspace_id": workspace["id"]})
    opened = mate.post(f"/api/browser/profiles/{profile_id}/opened", json={"url": "https://example.com"})
    assert opened.status_code == 200, opened.text
    assert opened.json()["is_mine"] is False


def test_no_actor_manages_nothing() -> None:
    class _Row:
        owner_user_id = None

    with SessionLocal() as db, pytest.raises(sharing.NotManageableError):
        sharing.ensure_manageable(db, "publish_account", _Row(), actor=None)
