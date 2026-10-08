"""工作区权限名写错了,当场报错 —— 不按最严的算,也不按最松的算。

此前 `ensure_workspace_perm` 收到表里没有的名字悄悄落到 admin:找、补预览图的任务由编辑者发起(要 `edit`),轮询结果那一步
写成了 `"view"`,于是编辑者自己发起的任务轮询拿到 403,而且说不出为什么。角色阶梯那一层反过来:`role_at_least` 收到不在
阶梯上的 `minimum` 按 -1 算,谁都够 —— 写错一个字就是放行所有人。这里钉住:

- 不认识的权限名、不认识的最低角色,当场 ValueError(是代码写错了,不是一次 403);
- 仓库里写死的权限名都在表里(ensure_workspace_perm / holds_workspace_perm 的第四个参数、各处 `perm=`、画板产出者的
  `permission=`):写错一个,这里红,不必等到有人在界面上撞见。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

RATCHET = True

from app.core.db import SessionLocal
from app.db.models import User
from app.domain.permissions import _PERM_ROLE, ensure_workspace_perm, holds_workspace_perm
from app.domain.roles import role_at_least
from tests.util import fresh_client

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def test_不认识的权限名当场报错_连主人也一样() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == "tester").one()
        ensure_workspace_perm(db, owner, workspace, "edit")
        for check in (ensure_workspace_perm, holds_workspace_perm):
            with pytest.raises(ValueError, match="unknown workspace permission 'view'"):
                check(db, owner, workspace, "view")


def test_不认识的最低角色当场报错_库里不认识的角色谁的门都过不了() -> None:
    with pytest.raises(ValueError, match="unknown workspace role 'admn'"):
        role_at_least("owner", "admn")
    assert role_at_least("editor", "viewer") and not role_at_least("viewer", "editor")
    assert not role_at_least("superuser", "viewer"), "库里记着一个不认识的角色:按最低算"


def _written_names(source: str) -> list[tuple[int, str]]:
    """源码里写死的工作区权限名(行号, 名字)。"""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        candidates = [keyword.value for keyword in node.keywords if keyword.arg == "perm"]
        if name in ("ensure_workspace_perm", "holds_workspace_perm", "_document_for") and len(node.args) >= 4:
            candidates.append(node.args[3])
        if name == "Producer":
            candidates += [keyword.value for keyword in node.keywords if keyword.arg == "permission"]
        found += [(node.lineno, one.value) for one in candidates
                  if isinstance(one, ast.Constant) and isinstance(one.value, str)]
    return found


def test_仓库里写死的权限名都在表里() -> None:
    unknown = [
        f"{path.relative_to(APP.parent)}:{line} {name!r}"
        for path in sorted(APP.rglob("*.py"))
        for line, name in _written_names(path.read_text(encoding="utf-8"))
        if name not in _PERM_ROLE
    ]
    assert unknown == [], f"这些权限名不在 permissions._PERM_ROLE 里(只读用 ensure_workspace_access):{unknown}"


def test_数法本身() -> None:
    source = '''
ensure_workspace_perm(db, user, ws, "edit")
holds_workspace_perm(db, user, ws, "view")
require_asset(db, user, asset_id, perm="upload")
Producer(id="x", permission="ai")
ConfirmableTool(name="y", permission="ai-cost")
ensure_workspace_perm(db, user, ws, chosen.permission)
'''
    assert [name for _line, name in _written_names(source)] == ["edit", "view", "upload", "ai"]
