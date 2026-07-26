"""浏览器池 Phase 1:持久档案(BrowserProfile)CRUD + 租约(一档案一活动会话)+ 发布账号迁移回填。

统一「持久登录身份」:发布账号 = 挂平台的档案(组合,非合并);通用档案任意站点复用。迁移沿用
同分区 persist:mibu-<accountId> —— 这条是本阶段最要命的不变量(发布登录态不能丢)。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal, _backfill_browser_pool
from app.db.models import BrowserProfile, BrowserSession, PublishAccount, Workflow
from app.domain import browser
from app.domain.publish import create_account
from app.domain.workflows import WorkflowDomainError, create_workflow
from app.domain.workflows.executors import get_executor
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


def test_new_publish_account_gets_pool_profile() -> None:
    """新建发布账号即建档挂靠:分区 persist:mibu-<id>,pool 页标注平台/账号。"""
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        acc = create_account(db, workspace_id=ws, platform="bilibili", name="B站主号", config={})
        acc_id = acc.id
        assert acc.profile_id is not None
        prof = db.get(BrowserProfile, acc.profile_id)
        assert prof.partition == f"persist:mibu-{acc_id}" and prof.name == "B站主号"
    pool = client.get(f"/api/browser/profiles?workspace_id={ws}").json()
    assert len(pool) == 1 and pool[0]["platform"] == "bilibili" and pool[0]["bound_account_id"] == acc_id


def test_backfill_relinks_legacy_account_preserving_partition() -> None:
    """老库里的发布账号(profile_id 为空)由回填补档,分区沿用 persist:mibu-<id> —— 登录不丢、幂等。"""
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        acc_id = create_account(db, workspace_id=ws, platform="bilibili", name="老号", config={}).id
        # 模拟老库:清掉自动建的档案与指针,回到「有账号、无档案」的历史态
        acc = db.get(PublishAccount, acc_id)
        db.delete(db.get(BrowserProfile, acc.profile_id))
        acc.profile_id = None
        db.commit()

    _backfill_browser_pool()

    with SessionLocal() as db:
        acc = db.get(PublishAccount, acc_id)
        assert acc.profile_id is not None
        assert db.get(BrowserProfile, acc.profile_id).partition == f"persist:mibu-{acc_id}"

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


def test_workflow_browser_open_pool_mode() -> None:
    """工作流 browser_open 的 pool 模式:在池档案分区上开会话,owner=workflow;缺档案报错。"""
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        pid = browser.create_profile(db, workspace_id=ws, name="流程用池号").id
        wf_id = create_workflow(db, workspace_id=ws, name="W", graph={"nodes": [], "edges": []}).id
    with SessionLocal() as db:
        wf = db.get(Workflow, wf_id)
        out = get_executor("browser_open")(db, wf, {"session_mode": "pool", "profile_id": pid})
        sess = db.get(BrowserSession, out["session"])
        assert sess.kind == "profile" and sess.profile_id == pid
        assert sess.owner_kind == "workflow" and sess.owner_id == wf_id
        assert sess.partition.startswith("persist:pool-")
    with SessionLocal() as db:
        wf = db.get(Workflow, wf_id)
        with pytest.raises(WorkflowDomainError):
            get_executor("browser_open")(db, wf, {"session_mode": "pool"})  # 缺 profile_id


def test_agent_pool_open_requires_confirmation_naming_identity() -> None:
    """智能体用池档案必须过确认卡(显式授权每会话):卡上点名是哪个档案;批准后才在其分区开会话。"""
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        pid = browser.create_profile(db, workspace_id=ws, name="采集号").id
    conf = client.post(
        "/api/confirmations",
        json={"workspace_id": ws, "tool": "browser_pool_open", "payload": {"profile_id": pid, "url": ""}},
    ).json()
    assert conf["status"] == "pending"
    assert "采集号" in conf["summary"] and "⚠️" in conf["summary"]  # 点名身份 + 跨信任边界警示
    approved = client.post(f"/api/confirmations/{conf['id']}/approve").json()
    assert approved["status"] == "executed"
    with SessionLocal() as db:
        sess = db.get(BrowserSession, approved["result"]["session_id"])
        assert sess.profile_id == pid and sess.kind == "profile" and sess.owner_kind == "agent"


def test_agent_pool_open_unknown_profile_rejected() -> None:
    client = fresh_client()
    ws = _ws(client)
    r = client.post(
        "/api/confirmations",
        json={"workspace_id": ws, "tool": "browser_pool_open", "payload": {"profile_id": "nope"}},
    )
    assert r.status_code == 422  # 档案不存在 → 连确认卡都不给建


def test_pool_agent_tools_in_manifest_and_gating() -> None:
    client = fresh_client()
    by_name = {tool["name"]: tool for tool in client.get("/api/agent/tools").json()}
    assert by_name.get("browser_pool_open", {}).get("confirmation") is True  # 用登录身份 → 必确认
    assert by_name.get("browser_pool_list", {}).get("confirmation") is False  # 只读发现 → 内联


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
