"""浏览器池 Phase 1:持久档案(BrowserProfile)CRUD + 租约(一档案一活动会话)+ 发布账号迁移回填。

统一「持久登录身份」:发布账号 = 挂平台的档案(组合,非合并);通用档案任意站点复用。迁移沿用
同分区 persist:mibu-<accountId> —— 这条是本阶段最要命的不变量(发布登录态不能丢)。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal, _backfill_browser_pool
from app.db.models import BrowserProfile, PublishAccount
from app.domain import browser
from app.domain.publish import create_account
from tests.util import fresh_client


def _ws(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_profile_crud_api() -> None:
    client = fresh_client()
    ws = _ws(client)
    r = client.post(
        "/api/browser/profiles",
        json={"workspace_id": ws, "name": "抖音小号", "proxy": "socks5://127.0.0.1:1080"},
    )
    assert r.status_code == 200, r.text
    prof = r.json()
    assert prof["name"] == "抖音小号"
    assert prof["partition"].startswith("persist:pool-")  # 通用档案分区
    assert prof["proxy"] == "socks5://127.0.0.1:1080"
    assert prof["enabled"] is True
    assert prof["platform"] is None  # 未绑发布平台 = 通用档案
    pid = prof["id"]

    assert [p["id"] for p in client.get(f"/api/browser/profiles?workspace_id={ws}").json()] == [pid]

    r = client.patch(f"/api/browser/profiles/{pid}", json={"name": "改名", "enabled": False})
    assert r.status_code == 200 and r.json()["name"] == "改名" and r.json()["enabled"] is False
    # proxy 显式置 null 才清空(未传则不动)
    assert client.patch(f"/api/browser/profiles/{pid}", json={"proxy": None}).json()["proxy"] is None

    assert client.delete(f"/api/browser/profiles/{pid}").status_code == 204
    assert client.get(f"/api/browser/profiles?workspace_id={ws}").json() == []


def test_backfill_migrates_publish_account_preserving_partition() -> None:
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        acc = create_account(db, workspace_id=ws, platform="bilibili", name="B站主号", config={})
        acc_id = acc.id
        assert acc.profile_id is None  # 本阶段新账号还没自动挂档案(step2 再接)

    _backfill_browser_pool()

    with SessionLocal() as db:
        acc = db.get(PublishAccount, acc_id)
        assert acc.profile_id is not None
        prof = db.get(BrowserProfile, acc.profile_id)
        assert prof is not None
        # 最要命的不变量:分区沿用 persist:mibu-<accountId>,Electron 打开同一分区,发布登录不丢
        assert prof.partition == f"persist:mibu-{acc_id}"
        assert prof.name == "B站主号"
        # pool 列表把它标注成发布账号
        pool = client.get(f"/api/browser/profiles?workspace_id={ws}").json()
        assert len(pool) == 1 and pool[0]["platform"] == "bilibili" and pool[0]["bound_account_id"] == acc_id

    _backfill_browser_pool()  # 幂等:再跑不重复建档
    with SessionLocal() as db:
        assert db.query(BrowserProfile).filter(BrowserProfile.workspace_id == ws).count() == 1


def test_profile_lease_one_active_session() -> None:
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        pid = browser.create_profile(db, workspace_id=ws, name="池号").id
    with SessionLocal() as db:
        s1 = browser.open_session(db, workspace_id=ws, profile_id=pid, owner_kind="agent", owner_id="A")
        assert s1.kind == "profile" and s1.partition.startswith("persist:pool-")
    with SessionLocal() as db:  # 同 owner 复用
        s2 = browser.open_session(db, workspace_id=ws, profile_id=pid, owner_kind="agent", owner_id="A")
        assert s2.id == s1.id
    with SessionLocal() as db:  # 异 owner → 占用中(租约)
        with pytest.raises(browser.BrowserDomainError):
            browser.open_session(db, workspace_id=ws, profile_id=pid, owner_kind="agent", owner_id="B")


def test_cannot_delete_bound_or_busy_profile() -> None:
    client = fresh_client()
    ws = _ws(client)
    # 绑定了发布账号 → 拒删
    with SessionLocal() as db:
        acc_id = create_account(db, workspace_id=ws, platform="bilibili", name="B", config={}).id
    _backfill_browser_pool()
    with SessionLocal() as db:
        bound_pid = db.get(PublishAccount, acc_id).profile_id
        with pytest.raises(browser.BrowserDomainError):
            browser.delete_profile(db, ws, bound_pid)
    # 有活动会话 → 拒删
    with SessionLocal() as db:
        pid = browser.create_profile(db, workspace_id=ws, name="忙").id
        browser.open_session(db, workspace_id=ws, profile_id=pid, owner_kind="agent", owner_id="A")
        with pytest.raises(browser.BrowserDomainError):
            browser.delete_profile(db, ws, pid)
