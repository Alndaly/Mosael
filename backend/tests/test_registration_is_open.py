"""注册开放,而空库时进「创建管理员」模式。

第 0 步曾把注册转成邀请制,理由是这条跑出来过的链的第一环:

    注册 → 自己建工作区(在里面是 owner)→ 满足当时那道自助的实例管理员判据
         → 改实例配置 / 存 code 节点 → 在服务端执行任意 Python

**那条链的中段和末段后来各自断了**:第 1 步把部署配置收到 `is_deployment_admin`(自己建工作区
不再带来任何部署权限),第 5 步把代码执行搬进隔离环境。于是"关掉注册"这一环不再是那条链的必要
条件 —— 它当时是止血,而止血的伤口已经缝上了。

现在的取舍变成一句普通的产品判断:陌生人能注册,拿到的是**他自己的**工作区,看不到别人的东西
(D3 归属)、用不了别人的钥匙(D4)、跑不了伤害别人的代码(D2)。想关的部署仍然关得掉。

**空库是另一件事**:那时没有任何人可以发邀请,而一个没有部署管理员的部署是块砖头。所以第一个
账号永远能建,而且界面该直说"你在创建这个部署的管理员",不是摆一个填不出来的邀请码框。
"""

from __future__ import annotations

from app.core.config import Settings, settings
from app.core.db import SessionLocal
from app.db.models import User
from tests.util import fresh_client, second_client


def test_registration_is_open_by_default() -> None:
    """默认开放 —— 关闭它现在是部署的选择,不再是产品的默认姿态。

    判据从 Settings 换成了库:开关搬进 DeploymentConfig,环境变量只在首次迁移时播种。
    """
    from app.db.models import DeploymentConfig

    assert DeploymentConfig.__table__.c.open_registration.default.arg is True


def test_a_stranger_can_register_once_someone_is_there() -> None:
    owner = fresh_client()
    owner.post("/api/workspaces", json={"name": "W"})
    joined = second_client("stranger")
    assert joined.get("/api/auth/me").status_code == 200


def test_a_deployment_can_still_close_it(monkeypatch) -> None:
    """关得掉:内网部署、或者就是不想让人自助进来 —— 现在在管理页里关,不必改环境变量。"""
    from app.core.db import SessionLocal
    from app.domain import deployment

    fresh_client()
    with SessionLocal() as db:
        deployment.set_open_registration(db, False)
        db.commit()
    refused = second_client.__wrapped__ if hasattr(second_client, "__wrapped__") else None
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    denied = client.post(
        "/api/auth/register", json={"username": "outsider", "display_name": "O", "password": "pw123456"}
    )
    assert denied.status_code == 403, denied.text
    assert "邀请码" in denied.text


# ---------------- 空库:创建管理员模式 ----------------


def test_a_fresh_deployment_says_it_needs_a_first_administrator() -> None:
    """界面据此换成「创建管理员账户」,而不是摆一个填不出来的邀请码框。"""
    client = fresh_client()
    with SessionLocal() as db:
        for person in db.query(User).all():
            db.delete(person)
        db.commit()

    state = client.get("/api/auth/bootstrap").json()
    assert state["has_users"] is False
    assert state["open_registration"] is True


def test_once_someone_is_there_it_is_no_longer_bootstrapping() -> None:
    client = fresh_client()
    assert client.get("/api/auth/bootstrap").json()["has_users"] is True


def test_the_registration_state_is_readable_without_logging_in() -> None:
    """登录页要用它 —— 那时当然还没有令牌。"""
    from fastapi.testclient import TestClient

    from app.main import app

    fresh_client()
    anonymous = TestClient(app)
    assert anonymous.get("/api/auth/bootstrap").status_code == 200


def test_the_first_account_still_becomes_the_deployment_administrator() -> None:
    """空库那一位引导整个部署 —— 没有部署管理员的部署是块砖头。"""
    client = fresh_client()
    with SessionLocal() as db:
        first = db.query(User).order_by(User.created_at).first()
        assert first.is_deployment_admin is True


def test_the_second_account_is_not_an_administrator() -> None:
    """开放注册**不等于**开放管理权:进来的是普通人。"""
    fresh_client()
    second_client("mate")
    with SessionLocal() as db:
        mate = db.query(User).filter(User.username == "mate").one()
        assert mate.is_deployment_admin is False


def test_a_stranger_still_cannot_touch_the_deployment() -> None:
    """开放注册之所以站得住,正是因为进来的人碰不到别人的东西、也碰不到这台机器。"""
    fresh_client()
    stranger = second_client("stranger2")
    stranger.post("/api/workspaces", json={"name": "他自己的"})
    assert stranger.put("/api/settings/network", json={"proxy_url": "http://x"}).status_code == 403
    assert stranger.get("/api/auth/users").status_code == 403
    # 他建得了**自己的**供应商连接(花他自己的钱),但看不到任何别人的。
    assert stranger.get("/api/settings/providers").json() == []
