"""角色即权限:四个角色,没有权限位矩阵。

此前是「四个角色 + 九个权限位 + 每人可覆盖」。删掉后两者,理由有三条:

  - **身份类资源搬出工作区之后,一半的位没有对应的能力了。** `credentials` 配的是自己的密钥,
    `publish` 用的是自己的账号(ADR 0008 D3)—— 它们不再是「工作区里谁能做什么」。
  - **剩下的位从来没人真的分开配过。** `upload / edit / delete / export / schedule` 之间的区分,
    在一个内容工作区里想不出真实场景:能改时间线却不能上传素材,是什么角色?
  - **它还养出了一个恒真条件。** editor 默认持有除 `members` 外的全部位,于是
    `ensure_instance_admin(db, user, perm)` 的第二个条件永远成立(已在第 1 步随判据一起清掉)。

新规则,四句话说完:

    viewer  读内容
    editor  读写内容,可以用智能体
    admin   editor + 改工作区设置、管成员
    owner   admin + 删除/转让工作区

**可逆**:真需要逐位配置时再加回来,那时会有真实用例说清楚要哪几位 —— 而不是先摆一个矩阵在这儿
等人来用。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.util import fresh_client, second_client


def _member(role: str) -> tuple[TestClient, dict, TestClient]:
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": role})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


# ---------------- viewer 只读 ----------------


def test_viewer_can_read() -> None:
    _owner, workspace, viewer = _member("viewer")
    assert viewer.get(f"/api/projects?workspace_id={workspace['id']}").status_code == 200


@pytest.mark.parametrize(
    "call",
    [
        lambda c, w: c.post("/api/projects", json={"workspace_id": w, "name": "P"}),
        lambda c, w: c.post("/api/agent/sessions", json={"workspace_id": w, "title": "T"}),
        lambda c, w: c.post("/api/workflows", json={"workspace_id": w, "name": "WF", "graph": {"nodes": [], "edges": []}}),
    ],
    ids=["建项目", "开对话", "建工作流"],
)
def test_viewer_cannot_write(call) -> None:
    _owner, workspace, viewer = _member("viewer")
    assert call(viewer, workspace["id"]).status_code == 403


# ---------------- editor 写内容 + 用智能体 ----------------


def test_editor_can_write_content() -> None:
    _owner, workspace, editor = _member("editor")
    assert editor.post("/api/projects", json={"workspace_id": workspace["id"], "name": "P"}).status_code == 200


def test_editor_can_use_the_agent() -> None:
    """「能改内容」与「能用智能体」不再分开配 —— 智能体就是改内容的另一只手。"""
    _owner, workspace, editor = _member("editor")
    assert editor.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).status_code == 200


def test_editor_cannot_manage_members() -> None:
    _owner, workspace, editor = _member("editor")
    denied = editor.post(
        f"/api/workspaces/{workspace['id']}/invitations", json={"username": "someone", "role": "viewer"}
    )
    assert denied.status_code == 403


# ---------------- admin 管工作区 ----------------


def test_admin_can_manage_members() -> None:
    _owner, workspace, admin = _member("admin")
    second_client("third")
    invited = admin.post(
        f"/api/workspaces/{workspace['id']}/invitations", json={"username": "third", "role": "viewer"}
    )
    assert invited.status_code == 200, invited.text


def test_admin_cannot_delete_the_workspace() -> None:
    """删工作区是 owner 的事 —— 它带走所有人的东西。"""
    _owner, workspace, admin = _member("admin")
    assert admin.delete(f"/api/workspaces/{workspace['id']}").status_code == 403


def test_owner_can_delete_the_workspace() -> None:
    owner, workspace, _admin = _member("admin")
    assert owner.delete(f"/api/workspaces/{workspace['id']}").status_code == 204


# ---------------- 矩阵确实消失了 ----------------


def test_there_is_no_permission_matrix_left() -> None:
    """删掉而不是留着不用:一个摆在那儿没人配的矩阵,只会让人以为它在起作用。"""
    import app.core.roles as roles

    assert not hasattr(roles, "PERMS"), "权限位常量还在"
    assert not hasattr(roles, "effective_perms"), "逐位求值还在"


def test_the_override_table_is_gone() -> None:
    from app.db import models

    assert not hasattr(models, "WorkspaceMemberPerm"), "每人覆盖表还在"


def test_the_members_api_no_longer_reports_perms() -> None:
    owner, workspace, _mate = _member("editor")
    info = owner.get(f"/api/workspaces/{workspace['id']}/members").json()
    assert "my_role" in info
    for member in info["members"]:
        assert "perms" not in member, member
