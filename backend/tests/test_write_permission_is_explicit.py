"""写权限是**写出来的**,不是从请求方法推出来的。

此前 `ensure_workspace_access` 自己判断:「当前请求是不是 POST/PUT/PATCH/DELETE?是就额外要 edit」。
那个方法名读自一个只在 ASGI 中间件里绑定的 ContextVar,**默认 GET**。跑出来:

    viewer 经 HTTP 写            403      ← 中间件绑上了 POST,闸门成立
    viewer 在后台线程里写         通过      ← 没有中间件,默认 GET

于是这道闸的正确性不取决于路由写了什么,而取决于**它碰巧是从哪儿被调用的**。今天所有写路由都
在 HTTP 上,所以它碰巧成立;而定时器、自动放行、工作流引擎、飞书回调都是后台线程 —— 那些路径上
同一个函数会安静地放行。

改法(ADR 0008 D5):`ensure_workspace_access` 退回成**只读闸**,任何成员都能过;要写的路由自己
点名 `ensure_workspace_perm(..., "edit")`。少一个"聪明"的推断,多 66 处显式声明。

底下这条棘轮是这一步的真正产出:**新加的写路由如果不点名权限,测试直接红**。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.core.db import SessionLocal
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import User
from fastapi import HTTPException
from tests.util import fresh_client, second_client

MUTATING = {"post", "put", "patch", "delete"}

#: 点名了权限的调用 —— 任何一个都算数。
EXPLICIT = {
    "ensure_workspace_perm",
    "ensure_workspace_role",
    "ensure_deployment_admin",
    "ensure_workspace_member",  # 只读语义,但它是显式的:调用点自己说了"只要是成员"
}

#: 取对象顺带过闸的辅助。它们带 `perm=` 时同样算"点名了" —— 权限写在调用点上,
#: 只是和"取哪个对象"合成了一行(见 core/permissions.require_sequence_access)。
GATED_HELPERS = {"require_sequence_access", "require_asset"}

#: **归属即权限**的那几个:东西归某个人,判据就是"它是不是我的",没有角色可言。
#: 它们各自是所在模块里唯一的取对象入口,取不到自己的就 404(见 settings._require_profile、
#: plugins.my_instance)。写在这里而不是让棘轮猜:漏掉一个的后果是那条路径能改别人的东西。
OWNERSHIP_GATES = {"_require_profile", "my_instance"}


def _local_gated_helpers(tree: ast.Module) -> set[str]:
    """这个模块自己的「取对象顺带过闸」辅助 —— 同样接受 `perm=`(见 routes/kb._require_dataset)。"""
    return {
        fn.name
        for fn in tree.body
        if isinstance(fn, ast.FunctionDef) and any(a.arg == "perm" for a in fn.args.kwonlyargs)
    }

#: 不作用在某个工作区上的写路由:账号自己的、部署级的、执行器回报通道、公开的引导接口。
#: 列在这里而不是让棘轮猜 —— 每加一条都得说清它为什么不属于任何工作区。
NOT_WORKSPACE_SCOPED = {
    "auth.py",           # 注册/登录/改自己的资料
    "deployment.py",     # 部署级:邀请码、部署管理员
    "settings.py",       # 部署级(网络/运行时/TTS)各自 ensure_deployment_admin;
                         # 供应商连接归人,判据是 _require_profile(见 OWNERSHIP_GATES)
    "publish_worker.py", # 桌面发布器的回报通道(独立的 worker key)
    "browser_worker.py", # 浏览器执行器的回报通道
    "jobs_worker.py",    # 外部任务执行器的回报通道
    "hooks.py",          # webhook:凭 token 触发,没有登录用户
    "workspaces.py",     # 建工作区本身(还没有工作区可查)、成员管理各自 ensure_workspace_role
    "invitations.py",    # 受邀人应答自己的邀请
    "notifications.py",  # 自己的通知
    "agent_credentials.py",  # 每个人自己的钥匙(见 domain/provider_credentials)
    "shares.py",         # 主人共享自己的东西(只认主人,不看角色)
    "job_worker.py",     # 外部任务执行器的认领/回报通道(独立的 worker key)
    "oauth.py",          # 第三方登录:还没有登录用户,更没有工作区
    "asr.py",            # 模型下载是部署级 —— 各自 ensure_deployment_admin
}

#: 闸在**领域内核**里而不是路由里的写路由。这不是放行,是把闸放在了更靠里的一层:
#: 内核对每一条调用路径生效(HTTP、飞书回调、自动放行),而路由只覆盖其中一条。
#: 每加一条都得指名道姓说清闸在哪个函数里。
GATED_IN_THE_DOMAIN = {
    # authorize_and_approve / authorize_and_reject 各自 ensure_workspace_perm(edit)
    "confirmations.py:approve",
    "confirmations.py:reject",
    # 建工作区时还没有工作区可查 —— 建的人成为它的 owner
    "projects.py:create_workspace",
    # 接一个插件时还没有这个接入可查 —— 建出来的就归建的人(见 db.models.PluginInstance)
    "plugins.py:create_instance",
}


def _names_a_permission(fn: ast.AST, gated: set[str]) -> bool:
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id in EXPLICIT or node.func.id in OWNERSHIP_GATES:
            return True
        if node.func.id in gated and any(k.arg == "perm" for k in node.keywords):
            return True
    return False


def _mutating_routes() -> list[tuple[str, str, bool]]:
    out: list[tuple[str, str, bool]] = []
    for path in sorted(pathlib.Path("app/api/routes").glob("*.py")):
        if path.name in NOT_WORKSPACE_SCOPED:
            continue
        tree = ast.parse(path.read_text())
        gated = GATED_HELPERS | _local_gated_helpers(tree)
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            verbs = {
                d.func.attr
                for d in fn.decorator_list
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            } & MUTATING
            if not verbs:
                continue
            out.append((path.name, fn.name, _names_a_permission(fn, gated)))
    return out


def test_every_mutating_route_names_the_permission_it_needs() -> None:
    """棘轮:新加的写路由必须自己点名权限。

    「靠 ensure_workspace_access 顺带挡住」不再算数 —— 它现在只管"是不是这个工作区的人"。
    """
    silent = [
        f"{module}:{fn}"
        for module, fn, explicit in _mutating_routes()
        if not explicit and f"{module}:{fn}" not in GATED_IN_THE_DOMAIN
    ]
    assert not silent, (
        "这些写路由没有点名它需要的权限(ensure_workspace_perm/…),"
        f"于是谁都能过:\n  " + "\n  ".join(sorted(silent))
    )


def test_the_read_gate_no_longer_guesses_from_the_request_method() -> None:
    """闸门不该读「当前请求是不是 POST」—— 那是环境,不是这次调用的意图。"""
    source = pathlib.Path("app/core/permissions.py").read_text()
    for ghost in ("_request_method", "bind_request_method", "_MUTATING"):
        assert ghost not in source, f"{ghost} 还在:写权限又会取决于调用它的是不是 HTTP 请求"


def test_a_viewer_cannot_write_even_off_the_http_path() -> None:
    """这条正是此前失效的那条:后台线程里没有请求方法可读。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    viewer = second_client("viewer")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "viewer", "role": "viewer"})
    invitation = viewer.get("/api/invitations").json()["invitations"][0]
    viewer.post(f"/api/invitations/{invitation['id']}/accept")

    with SessionLocal() as db:
        person = db.query(User).filter(User.username == "viewer").one()
        # 读:通过 —— viewer 本来就该读得到。
        ensure_workspace_access(db, person, workspace["id"])
        # 写:拒绝,而且**与是不是 HTTP 请求无关**。
        with pytest.raises(HTTPException) as caught:
            ensure_workspace_perm(db, person, workspace["id"], "edit")
        assert caught.value.status_code == 403


def test_an_editor_still_writes() -> None:
    """别把它锁死:editor 该能写的照样能写。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    project = mate.post("/api/projects", json={"workspace_id": workspace["id"], "name": "P"})
    assert project.status_code == 200, project.text
    made = mate.post(
        "/api/sequences",
        json={"workspace_id": workspace["id"], "project_id": project.json()["id"], "name": "S"},
    )
    assert made.status_code == 200, made.text
