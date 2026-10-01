"""具名 / 池档案会话的租约落在库里:同一份登录(分区)上最多一个开着的会话。

此前只靠「先查后建」:同一拍的两次打开都查到「没有」、各建一个,同一份登录上就开着两个会话(实测过)——
两次运行在同一个视图上互相点、互相导航。现在由局部唯一索引挡下后到的那个,它按此刻占着的是谁判:
同 owner 复用,别人就是「被占用」。
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_browser_sessions_one_open_per_login
from app.db.models import BrowserAction, BrowserSession, User
from app.domain import browser
from tests.util import fresh_client


def _ws() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _open_concurrently(monkeypatch, open_one) -> tuple[list[str], list[str]]:
    """两条线程同时打开:都先查完「有没有人占着」,再一起往下走(屏障卡在那一次查询之后)。"""
    barrier = threading.Barrier(2)
    original = SessionLocal.class_.scalar
    waited: set[str] = set()

    def scalar_then_wait(self, stmt, *args, **kwargs):
        result = original(self, stmt, *args, **kwargs)
        me = threading.current_thread().name
        if "browser_sessions" in str(stmt) and me.startswith("opener") and me not in waited:
            waited.add(me)  # 只卡第一次查;撞上索引之后的那次照常走
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(SessionLocal.class_, "scalar", scalar_then_wait)
    opened: list[str] = []
    errors: list[str] = []

    def go(owner: str) -> None:
        try:
            with SessionLocal() as db:
                opened.append(open_one(db, owner).id)
        except browser.BrowserDomainError as exc:
            errors.append(exc.key)

    threads = [threading.Thread(target=go, args=(f"run-{i}",), name=f"opener-{i}") for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    monkeypatch.setattr(SessionLocal.class_, "scalar", original)
    return opened, errors


def _open_rows(partition: str) -> list[BrowserSession]:
    with SessionLocal() as db:
        return list(
            db.scalars(select(BrowserSession).where(BrowserSession.partition == partition, BrowserSession.status == "open"))
        )


def test_同一拍打开同一个具名会话_只开出一个_后到的报被占用(monkeypatch) -> None:
    ws = _ws()
    opened, errors = _open_concurrently(
        monkeypatch,
        lambda db, owner: browser.open_session(
            db, workspace_id=ws, kind="named", name="xhs", owner_kind="workflow", owner_id=owner, actor=None
        ),
    )
    assert len(opened) == 1 and errors == ["browserErr_sessionBusy"]
    assert [row.id for row in _open_rows(browser.named_partition(ws, "xhs"))] == opened


def test_同一拍打开同一个池档案_只开出一个_后到的报被占用(monkeypatch) -> None:
    ws = _ws()
    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == "tester").one()
        profile = browser.create_profile(db, workspace_id=ws, name="号", owner=owner)
        db.commit()
        profile_id, partition, owner_id = profile.id, profile.partition, owner.id
    opened, errors = _open_concurrently(
        monkeypatch,
        lambda db, run: browser.open_session(
            db, workspace_id=ws, profile_id=profile_id, owner_kind="workflow", owner_id=run, actor=owner_id
        ),
    )
    assert len(opened) == 1 and errors == ["browserErr_profileBusy"]
    assert [row.id for row in _open_rows(partition)] == opened


def test_同一个owner同一拍打开两次_拿到的是同一个会话(monkeypatch) -> None:
    ws = _ws()
    opened, errors = _open_concurrently(
        monkeypatch,
        lambda db, _owner: browser.open_session(
            db, workspace_id=ws, kind="named", name="xhs", owner_kind="workflow", owner_id="run-1", actor=None
        ),
    )
    assert errors == [] and len(set(opened)) == 1


def test_库里直接插第二个开着的具名会话_被索引拒绝() -> None:
    ws = _ws()
    with SessionLocal() as db:
        browser.open_session(db, workspace_id=ws, kind="named", name="xhs", owner_kind="workflow", owner_id="a", actor=None)
    with SessionLocal() as db:
        db.add(BrowserSession(workspace_id=ws, kind="named", name="xhs", partition=browser.named_partition(ws, "xhs"),
                              owner_kind="workflow", owner_id="b", status="open"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_迁移_先收掉已经撞上的_每份登录留最早开的那个_再建索引() -> None:
    ws = _ws()
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS uq_browser_sessions_open_login"))
        for sid, at in (("s-old", "2026-01-01 00:00:00"), ("s-new", "2026-01-02 00:00:00")):
            conn.execute(
                text(
                    "INSERT INTO browser_sessions (id, workspace_id, kind, name, partition, owner_kind, owner_id, status, "
                    "last_url, created_at, updated_at) VALUES (:id, :ws, 'named', 'xhs', 'persist:rpa-x', 'workflow', :id, "
                    "'open', '', :at, :at)"
                ),
                {"id": sid, "ws": ws, "at": at},
            )
        # 临时会话不在其列:同一个分区名也不该被收
        conn.execute(
            text(
                "INSERT INTO browser_sessions (id, workspace_id, kind, name, partition, owner_kind, status, last_url, "
                "created_at, updated_at) VALUES ('s-eph', :ws, 'ephemeral', '', 'ephemeral-1', 'agent', 'open', '', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            ),
            {"ws": ws},
        )
    with SessionLocal() as db:
        db.add(BrowserAction(session_id="s-new", workspace_id=ws, action="click", args={}, status="queued"))
        db.commit()

    _migrate_browser_sessions_one_open_per_login()
    _migrate_browser_sessions_one_open_per_login()  # 重复跑无害

    with SessionLocal() as db:
        assert db.get(BrowserSession, "s-old").status == "open"
        assert db.get(BrowserSession, "s-new").status == "closed"
        assert db.get(BrowserSession, "s-eph").status == "open"
        action = db.query(BrowserAction).filter(BrowserAction.session_id == "s-new").one()
        assert (action.status, action.error) == ("failed", "browserErr_sessionClosed")
    with engine.connect() as conn:
        names = {row[1] for row in conn.execute(text("PRAGMA index_list('browser_sessions')"))}
    assert "uq_browser_sessions_open_login" in names
