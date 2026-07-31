from __future__ import annotations

import threading
import time

import pytest

from app.domain.provider_auth import (
    CredentialLeaseError,
    acquire_lease,
    commit_credential,
    read_credential,
    release_lease,
)
from app.domain.providers import auth_types_for_vendor, normalize_auth_type, pi_provider_id

"""OAuth 凭据的互斥刷新。

这里要挡的是一个**偶发、难复现、后果却是「刚登录就被登出」**的故障:订阅制的 refresh token
多为一次性 —— 换出新 access token 的同时旧 refresh 立刻作废。Open Studio 每轮对话新起一个
sidecar,而对话页 / 工作流 / 飞书可以同时开工;两个 sidecar 拿同一份凭据同时刷新时,后手会让
先手刚存好的那份当场失效。

版本号式的乐观并发在这里不够用:冲突要到写入时才发现,而那时两次刷新的网络请求都已经发出去了。
所以判据是**第二个刷新者根本进不来**,而不是「进得来但写入被拒」。
"""


def _profile(client, vendor: str = "kimi-coding") -> str:
    resp = client.post(
        "/api/settings/providers",
        json={"name": "订阅测试", "vendor": vendor, "config": {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_vendor_declares_its_auth_types() -> None:
    """订阅制预设声明 oauth;老的十几个 vendor 没声明,一律按 api_key 处理(不能因为新增字段就全变)。"""
    assert auth_types_for_vendor("kimi-coding")[0] == "oauth"
    assert auth_types_for_vendor("openai") == ["api_key"]
    assert auth_types_for_vendor("不存在的厂商") == ["api_key"]


def test_auth_type_is_confined_to_what_the_vendor_supports() -> None:
    """给 openai 传 oauth 不该被接受 —— 它没有可跑的授权流程,存下来只会在开对话时才炸。"""
    assert normalize_auth_type("openai", "oauth") == "api_key"
    assert normalize_auth_type("kimi-coding", "oauth") == "oauth"
    assert normalize_auth_type("kimi-coding", None) == "oauth"


def test_only_subscription_vendors_map_to_a_pi_provider() -> None:
    assert pi_provider_id("kimi-coding") == "kimi-coding"
    assert pi_provider_id("openai-compatible") == ""


def test_second_refresher_cannot_enter_while_the_first_holds_it() -> None:
    """核心判据:持锁期间别人拿不到租约。拿得到就意味着两次刷新会同时打网络。"""
    token = acquire_lease("p1")
    try:
        with pytest.raises(CredentialLeaseError):
            acquire_lease("p1", timeout=0.2)
    finally:
        release_lease("p1", token)
    # 释放后立刻可再取
    second = acquire_lease("p1", timeout=0.2)
    release_lease("p1", second)


def test_different_profiles_do_not_block_each_other() -> None:
    a = acquire_lease("p-a")
    b = acquire_lease("p-b", timeout=0.2)
    release_lease("p-a", a)
    release_lease("p-b", b)


def test_a_dead_holder_does_not_lock_the_provider_forever(monkeypatch) -> None:
    """持有者会崩(sidecar 被杀、超时)。没有 TTL 的话一次崩溃就让该供应商永久不可刷新。"""
    import app.domain.provider_auth as mod

    monkeypatch.setattr(mod, "LEASE_TTL_SECONDS", 0.05)
    acquire_lease("p-dead")  # 拿了就"死"了,永不释放
    time.sleep(0.08)
    revived = acquire_lease("p-dead", timeout=0.5)
    release_lease("p-dead", revived)


def test_waiter_gets_in_as_soon_as_the_holder_releases() -> None:
    """不是靠轮询超时才进去,而是持有者一放手就进 —— 否则每轮对话要白等一个 TTL。"""
    held = acquire_lease("p-wait")
    entered: list[float] = []

    def waiter() -> None:
        token = acquire_lease("p-wait", timeout=3.0)
        entered.append(time.monotonic())
        release_lease("p-wait", token)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.15)
    released_at = time.monotonic()
    release_lease("p-wait", held)
    thread.join(timeout=3)
    assert entered, "等待者没能进入临界区"
    assert entered[0] - released_at < 0.5, "释放后进入得太慢,说明是靠超时而不是靠让位"


def test_stale_lease_cannot_overwrite_the_new_holders_credential(client_fixture) -> None:
    """租约超时被顶替后,老持有者的写入必须被拒 —— 否则它会把别人刚刷出来的凭据覆盖成作废的那份。"""
    from app.core.db import SessionLocal

    client, profile_id = client_fixture
    stale = acquire_lease(profile_id)
    release_lease(profile_id, stale)  # 模拟超时后被顶替
    fresh = acquire_lease(profile_id)
    with SessionLocal() as db:
        with pytest.raises(CredentialLeaseError):
            commit_credential(db, profile_id, stale, {"type": "oauth", "access": "旧的"})
        commit_credential(db, profile_id, fresh, {"type": "oauth", "access": "新的", "refresh": "r", "expires": 1})


def test_credential_round_trips_verbatim(client_fixture) -> None:
    """各家 OAuth 的附加字段由 pi 解释;这里拆一次就等于把六家协议复制进 Python,上游加字段会悄悄丢。"""
    from app.core.db import SessionLocal

    client, profile_id = client_fixture
    credential = {
        "type": "oauth",
        "access": "a",
        "refresh": "r",
        "expires": 123,
        "endpoint": "https://copilot.example",  # 各家自带的附加字段
        "account_id": "acc",
    }
    lease = acquire_lease(profile_id)
    with SessionLocal() as db:
        profile = commit_credential(db, profile_id, lease, credential)
        assert read_credential(profile) == credential


def test_garbage_is_not_stored_as_a_credential(client_fixture) -> None:
    from app.core.db import SessionLocal

    client, profile_id = client_fixture
    lease = acquire_lease(profile_id)
    with SessionLocal() as db:
        with pytest.raises(CredentialLeaseError):
            commit_credential(db, profile_id, lease, {"access": "没有 type"})


def test_switching_to_api_key_clears_the_oauth_credential(client_fixture) -> None:
    """否则「已登录」的显示会说谎:切回 API Key 后那份令牌既用不上,又还在库里。"""
    from app.core.db import SessionLocal

    client, profile_id = client_fixture
    lease = acquire_lease(profile_id)
    with SessionLocal() as db:
        commit_credential(db, profile_id, lease, {"type": "oauth", "access": "a", "refresh": "r", "expires": 1})
    assert client.get("/api/settings/providers").json()[0]["oauth_linked"] is True

    resp = client.patch(f"/api/settings/providers/{profile_id}", json={"auth_type": "api_key"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["auth_type"] == "api_key"
    assert resp.json()["oauth_linked"] is False


def test_the_api_never_hands_back_the_token(client_fixture) -> None:
    """凭据只进不出:接口只回「登上了没有」。"""
    from app.core.db import SessionLocal

    client, profile_id = client_fixture
    lease = acquire_lease(profile_id)
    with SessionLocal() as db:
        commit_credential(db, profile_id, lease, {"type": "oauth", "access": "机密令牌", "refresh": "r", "expires": 1})
    body = client.get("/api/settings/providers").text
    assert "机密令牌" not in body


@pytest.fixture
def client_fixture():
    from tests.util import fresh_client

    client = fresh_client()
    # 供应商配置属于实例级设置,要求调用者在某个工作区里是 admin/owner(见 ensure_instance_admin)。
    client.post("/api/workspaces", json={"name": "W"})
    return client, _profile(client)
