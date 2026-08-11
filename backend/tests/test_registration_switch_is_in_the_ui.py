"""「开不开放自助注册」在管理页里改,不必去改环境变量重启后端。

它此前只读 `OPEN_STUDIO_OPEN_REGISTRATION`。一个只能改环境变量的开关意味着:改它要能碰到部署
机、要重启进程 —— 而这是一个**部署管理员在界面上就该能做的决定**,和发邀请码、授予管理员
是同一类事。

**库是唯一真相,环境变量只作首次播种。** 老部署设过那个变量的,迁移时按它建初始行,之后以库
为准 —— 不做"两边都读"的兼容:那样一个部署会同时有两个答案,而谁赢取决于代码里的顺序。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.util import fresh_client, second_client


def test_an_admin_can_close_and_reopen_it() -> None:
    admin = fresh_client()
    assert admin.get("/api/auth/bootstrap").json()["open_registration"] is True

    assert admin.put("/api/admin/registration", json={"open": False}).status_code == 200
    assert admin.get("/api/auth/bootstrap").json()["open_registration"] is False

    denied = TestClient(app).post(
        "/api/auth/register", json={"username": "outsider", "display_name": "O", "password": "pw123456"}
    )
    assert denied.status_code == 403 and "邀请码" in denied.text

    admin.put("/api/admin/registration", json={"open": True})
    assert TestClient(app).post(
        "/api/auth/register", json={"username": "welcome", "display_name": "W", "password": "pw123456"}
    ).status_code == 200


def test_an_ordinary_member_cannot_touch_it() -> None:
    """谁能进这个部署,是部署级的决定。"""
    fresh_client()
    mate = second_client("mate")
    assert mate.put("/api/admin/registration", json={"open": False}).status_code == 403


def test_the_env_var_only_seeds_the_first_row(monkeypatch) -> None:
    """老部署设过环境变量的,迁移按它建初始行;之后**以库为准**。

    不做"两边都读":那样一个部署会同时有两个答案,而谁赢取决于代码里的顺序。
    """
    from app.core.db import engine
    from app.db.migrations import _migrate_deployment_config
    from sqlalchemy import text

    admin = fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM deployment_config"))
    monkeypatch.setenv("OPEN_STUDIO_OPEN_REGISTRATION", "0")
    _migrate_deployment_config()
    assert admin.get("/api/auth/bootstrap").json()["open_registration"] is False

    # 库里已经有行之后,环境变量再变也不影响 —— 它只播种一次。
    monkeypatch.setenv("OPEN_STUDIO_OPEN_REGISTRATION", "1")
    _migrate_deployment_config()
    assert admin.get("/api/auth/bootstrap").json()["open_registration"] is False


def test_the_ui_actually_has_the_switch() -> None:
    """文件名说的是「在界面里」—— 那就守住这一条,而不只是守住路由存在。

    一个只有后端的开关和一个只有环境变量的开关,对使用者是同一件事:改不了。同时守住旧文案
    不再回来 —— 它教人去改 OPEN_STUDIO_OPEN_REGISTRATION。
    """
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src"
    section = (frontend / "features/settings/DeploymentSection.tsx").read_text()
    assert '"/api/admin/registration"' in section, "管理页没有调这个开关"
    assert "deployRegistrationOpen" in section

    for name in ("app/messages.ts", "features/settings/DeploymentSection.tsx"):
        text = (frontend / name).read_text()
        assert "OPEN_STUDIO_OPEN_REGISTRATION" not in text, f"{name} 还在教人改环境变量"
