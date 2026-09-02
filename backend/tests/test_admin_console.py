"""管理员控制台:谁在用这个部署、用的什么版本、花了多少。

它和「设置」是两件事,所以不该挤在设置页里:设置是**我**怎么用这个应用(外观、我的密钥、我的
默认模型);管理员看的是**这台部署**的状况 —— 谁进来了、谁在花钱、谁的客户端还停在旧版本。

**客户端版本必须由客户端自己报**。后端知道的那个 `app_version` 是它自己进程的版本;分布式部署
里每个人跑的壳可以各不相同,而"某人还停在 0.7"正是管理员要看的东西 —— 它解释了为什么只有他
撞得到那个早就修好的 bug。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import User
from app.main import app
from tests.util import fresh_client, second_client


def _admin_and_member() -> tuple[TestClient, TestClient]:
    admin = fresh_client()
    admin.post("/api/workspaces", json={"name": "W"})
    mate = second_client("mate")
    return admin, mate


# ---------------- 只有管理员看得到 ----------------


def test_an_ordinary_member_cannot_open_the_console() -> None:
    _admin, mate = _admin_and_member()
    assert mate.get("/api/admin/overview").status_code == 403
    assert mate.get("/api/admin/users").status_code == 403


def test_a_deployment_admin_can() -> None:
    admin, _mate = _admin_and_member()
    assert admin.get("/api/admin/overview").status_code == 200
    assert admin.get("/api/admin/users").status_code == 200


# ---------------- 每个人用的客户端版本 ----------------


def test_the_client_reports_its_own_version() -> None:
    """版本由客户端在请求头里报 —— 后端进程的版本回答不了"**他**装的是哪一版"。"""
    admin, mate = _admin_and_member()
    mate.headers["X-Mosael-Client"] = "0.7.3"
    mate.get("/api/auth/me")

    rows = {row["username"]: row for row in admin.get("/api/admin/users").json()}
    assert rows["mate"]["client_version"] == "0.7.3"


def test_a_newer_version_replaces_the_old_one() -> None:
    """他升级了就该显示新的 —— 这一栏说的是"他现在跑的是哪一版"。"""
    admin, mate = _admin_and_member()
    mate.headers["X-Mosael-Client"] = "0.7.3"
    mate.get("/api/auth/me")
    mate.headers["X-Mosael-Client"] = "0.9.1"
    mate.get("/api/auth/me")

    rows = {row["username"]: row for row in admin.get("/api/admin/users").json()}
    assert rows["mate"]["client_version"] == "0.9.1"


def test_a_client_that_never_says_leaves_it_blank() -> None:
    """老客户端不报版本。空着,而不是编一个 —— "不知道"和"0.0.0"是两回事。"""
    admin, mate = _admin_and_member()
    mate.get("/api/auth/me")
    rows = {row["username"]: row for row in admin.get("/api/admin/users").json()}
    assert rows["mate"]["client_version"] == ""


def test_a_junk_version_string_does_not_get_stored() -> None:
    """请求头是外部输入。只收像版本号的,别让它变成一条能塞任意文本的通道。"""
    admin, mate = _admin_and_member()
    mate.headers["X-Mosael-Client"] = "<script>alert(1)</script>" + "x" * 500
    mate.get("/api/auth/me")
    rows = {row["username"]: row for row in admin.get("/api/admin/users").json()}
    assert rows["mate"]["client_version"] == ""


def test_last_seen_follows_the_person() -> None:
    """"他还在用吗" —— 停用一个账号之前总要先知道这个。"""
    admin, mate = _admin_and_member()
    mate.get("/api/auth/me")
    rows = {row["username"]: row for row in admin.get("/api/admin/users").json()}
    assert rows["mate"]["last_seen_at"]


# ---------------- 统计 ----------------


def test_the_overview_counts_what_an_admin_actually_needs() -> None:
    admin, mate = _admin_and_member()
    mate.get("/api/auth/me")
    overview = admin.get("/api/admin/overview").json()

    assert overview["users"] == 2
    assert overview["active_users_7d"] >= 1
    assert "workspaces" in overview and "assets" in overview
    # 花销按人分,而不是只给一个总数 —— 管理员要回答的是"谁在花"。
    assert isinstance(overview["spend_by_user"], list)
    assert isinstance(overview["jobs_by_day"], list)


def test_the_charts_have_a_bounded_window() -> None:
    """图表拉的是最近 N 天,不是全表 —— 一个跑了两年的部署不该在打开这一页时扫全库。"""
    admin, _mate = _admin_and_member()
    overview = admin.get("/api/admin/overview").json()
    assert len(overview["jobs_by_day"]) <= 30
