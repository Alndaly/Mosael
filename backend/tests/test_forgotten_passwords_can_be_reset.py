"""忘了密码有路可走(体检 UM-04):部署管理员在管理页替成员重置,唯一的管理员被锁在外面时用后端命令行。

此前登录页没有入口,管理员也改不了别人的密码 —— 成员只能被删号重来(连同他的对话、密钥、只有他一个人的
工作区),唯一的部署管理员忘了密码就整台锁死、只能手改数据库。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import cli
from app.main import app
from tests.util import PASSWORD, fresh_client, second_client


def _login(username: str, password: str) -> int:
    return TestClient(app).post("/api/auth/login", json={"username": username, "password": password}).status_code


def test_部署管理员替成员重置_拿到临时密码_旧密码和旧会话一起作废() -> None:
    admin = fresh_client("admin")
    member = second_client("member")
    member_id = member.get("/api/auth/me").json()["id"]

    reset = admin.post(f"/api/admin/users/{member_id}/password")
    assert reset.status_code == 200, reset.text
    temporary = reset.json()["password"]
    assert len(temporary) >= 12

    assert member.get("/api/auth/me").status_code == 401, "他手上的旧会话要一起作废"
    assert _login("member", PASSWORD) == 401
    assert _login("member", temporary) == 200


def test_只有部署管理员能重置_也不在这里重置自己() -> None:
    admin = fresh_client("admin")
    admin_id = admin.get("/api/auth/me").json()["id"]
    member = second_client("member")
    other = second_client("other")
    other_id = other.get("/api/auth/me").json()["id"]

    assert member.post(f"/api/admin/users/{other_id}/password").status_code == 403
    assert _login("other", PASSWORD) == 200, "没重置成就什么都不该变"
    own = admin.post(f"/api/admin/users/{admin_id}/password", headers={"Accept-Language": "zh-CN"})
    assert own.status_code == 409 and "设置 → 账户" in own.json()["detail"]
    assert admin.post("/api/admin/users/nope/password").status_code == 404


def test_命令行兜底_唯一的管理员忘了密码(capsys) -> None:
    admin = fresh_client("admin")

    assert cli.main(["reset-password", "ADMIN ", "--password", "new-secret-1"]) == 0
    printed = capsys.readouterr().out
    assert "new-secret-1" in printed
    assert admin.get("/api/auth/me").status_code == 401
    assert _login("admin", "new-secret-1") == 200

    assert cli.main(["reset-password", "admin"]) == 0
    generated = capsys.readouterr().out.split("New password: ")[1].split()[0]
    assert _login("admin", generated) == 200

    assert cli.main(["reset-password", "ghost"]) == 1
    assert "admin" in capsys.readouterr().err, "认错用户名时列出这台部署上有哪些账号"
    assert cli.main(["reset-password", "admin", "--password", "abc"]) == 2
    assert _login("admin", generated) == 200
