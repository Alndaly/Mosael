"""`AuthSession` 里的每一行都必须会过期。

这张表存的是"谁登录了"和"哪个子进程可以回连"——两者是同一种权力。它此前没有过期列,于是
每一行都是**永久**凭据,而"用完删掉"就成了每个铸造点各自的责任:对话轮次记得删(host.py
结尾),工具通道忘了(一次调用一行),OAuth 刷新、查额度、订阅登录三处也忘了。同一个缺陷
发作五次,补丁要写五份,而漏掉一份没有任何东西会报错。

根因是这张表本身。过期由表来保证之后:

  - 忘记撤销不再等于泄漏一把永久钥匙,最多是它多活一会儿;
  - 增长自限——铸新行时顺手清掉已过期的;
  - 撤销仍然值得做(轮次结束就删比等 30 分钟更紧),但它从"必须"降级为"更好"。

服务令牌和登录令牌的周期差着三个数量级,因为它们的用途根本不同:前者是一次有界操作的
凭据,后者是"这个人还在用这台机器"。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.core.security import (
    LOGIN_SESSION_TTL,
    SERVICE_SESSION_TTL,
    find_session,
    mint_service_session,
    prune_expired_sessions,
)
from app.db.models import AuthSession, User, now
from tests.util import PASSWORD, fresh_client


def _row(token: str) -> AuthSession | None:
    """按**来客手上那串**取行 —— 库里存的是它的哈希(见 core/tokens),主键不再是令牌本身。"""
    with SessionLocal() as db:
        return find_session(db, token)


def _expire(token: str, *, by: timedelta = timedelta(seconds=1)) -> None:
    with SessionLocal() as db:
        row = find_session(db, token)
        row.expires_at = now() - by
        db.commit()


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def test_logging_in_creates_a_session_that_expires() -> None:
    client = fresh_client()
    token = client.headers["Authorization"].removeprefix("Bearer ")

    row = _row(token)
    assert row is not None
    assert row.kind == "login"
    assert row.expires_at > now(), "登录会话一建出来就是过期的"
    assert row.expires_at <= now() + LOGIN_SESSION_TTL


def test_service_tokens_are_short_lived() -> None:
    """子进程拿的是一次有界操作的凭据,不该和"这个人登录着"同一个周期。"""
    fresh_client()
    with SessionLocal() as db:
        token = mint_service_session(db, _user_id("tester"))

    row = _row(token)
    assert row is not None and row.kind == "service"
    assert row.expires_at <= now() + SERVICE_SESSION_TTL
    assert SERVICE_SESSION_TTL < LOGIN_SESSION_TTL / 10, "服务令牌的周期没有明显短于登录"


def test_an_expired_token_is_rejected_and_swept() -> None:
    client = fresh_client()
    token = client.headers["Authorization"].removeprefix("Bearer ")
    _expire(token)

    assert client.get("/api/workspaces").status_code == 401
    assert _row(token) is None, "过期的行被拒了却还留在库里"


def test_minting_prunes_what_has_already_expired() -> None:
    """增长自限:表变大的时刻恰好是清理的时刻,不需要一个定时任务来兜底。"""
    fresh_client()
    user_id = _user_id("tester")
    with SessionLocal() as db:
        stale = mint_service_session(db, user_id)
    _expire(stale)

    with SessionLocal() as db:
        fresh = mint_service_session(db, user_id)

    assert _row(stale) is None, "铸新令牌时没有清掉已经过期的"
    assert _row(fresh) is not None


def test_an_active_login_is_renewed_rather_than_cut_off() -> None:
    """滑动续期:用着用着被登出是回归,不是安全。"""
    client = fresh_client()
    token = client.headers["Authorization"].removeprefix("Bearer ")
    # 逼近过期(剩余不足半个周期)——这时下一次请求应当把它续上。
    with SessionLocal() as db:
        row = find_session(db, token)
        row.expires_at = now() + timedelta(minutes=1)
        db.commit()

    assert client.get("/api/workspaces").status_code == 200

    renewed = _row(token)
    assert renewed is not None
    assert renewed.expires_at > now() + LOGIN_SESSION_TTL / 2, "活跃使用没有把登录续上"


def test_service_tokens_do_not_slide() -> None:
    """服务令牌被反复使用不该把它变成长期凭据 —— 它的周期由那次操作决定,不由用量决定。"""
    client = fresh_client()
    with SessionLocal() as db:
        token = mint_service_session(db, _user_id("tester"))
    before = _row(token).expires_at

    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/api/workspaces").status_code == 200

    assert _row(token).expires_at == before, "服务令牌被续期了"


def test_pruning_leaves_live_sessions_alone() -> None:
    client = fresh_client()
    live = client.headers["Authorization"].removeprefix("Bearer ")
    with SessionLocal() as db:
        dead = mint_service_session(db, _user_id("tester"))
    _expire(dead)

    with SessionLocal() as db:
        removed = prune_expired_sessions(db)
        db.commit()

    assert removed >= 1
    assert _row(dead) is None
    assert _row(live) is not None


def test_logging_out_still_works() -> None:
    """过期不是撤销的替代品 —— 主动登出必须立刻生效。"""
    client = fresh_client()
    token = client.headers["Authorization"].removeprefix("Bearer ")
    assert client.post("/api/auth/logout").status_code == 200
    assert _row(token) is None
    assert client.get("/api/workspaces").status_code == 401


def test_a_second_login_does_not_disturb_the_first() -> None:
    """同一个人可以有多份会话(桌面 + 飞书),清理不能误伤其中任何一份。"""
    from fastapi.testclient import TestClient

    from app.main import app

    first = fresh_client()
    first_token = first.headers["Authorization"].removeprefix("Bearer ")

    second = TestClient(app)
    logged_in = second.post("/api/auth/login", json={"username": "tester", "password": PASSWORD})
    assert logged_in.status_code == 200, logged_in.text

    assert _row(first_token) is not None
    assert _row(logged_in.json()["token"]) is not None
