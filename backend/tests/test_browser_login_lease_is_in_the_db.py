"""具名 / 池档案会话的租约落在库里:同一份登录(分区)上最多一个开着的会话。

此前只靠「先查后建」:同一拍的两次打开都查到「没有」、各建一个,同一份登录上就开着两个会话(实测过)——
两次运行在同一个视图上互相点、互相导航。现在判和建在同一个 BEGIN IMMEDIATE 事务里(后到的排在写锁上,轮到它时
看到的是前一个建好的那一行),同 owner 复用,别人就是「被占用」;局部唯一索引兜底绕开这条路的写入。
"""

from __future__ import annotations

import threading
import time

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


ROUNDS = 20


def _open_concurrently(open_one, *, rounds: int = ROUNDS) -> list[tuple[list[str], list[str], list[str]]]:
    """两条线程同一拍打开,跑 `rounds` 轮。每轮交回 (开出来的会话 id, 领域错误的 key, 别的异常)。

    屏障放在打开**之前**:两边一起进 open_session,谁先拿到租约看调度 —— 跑二十轮,把各种先后都碰一遍。
    「别的异常」必须一条都没有:此前满负载下后到的那个报的是 sqlite 的 database is locked。
    """
    return [_one_round(open_one, round_no) for round_no in range(rounds)]


def _one_round(open_one, round_no: int) -> tuple[list[str], list[str], list[str]]:
    barrier = threading.Barrier(2)
    opened: list[str] = []
    errors: list[str] = []
    crashes: list[str] = []

    def go(owner: str) -> None:
        barrier.wait(timeout=10)
        try:
            with SessionLocal() as db:
                opened.append(open_one(db, owner, round_no).id)
        except browser.BrowserDomainError as exc:
            errors.append(exc.key)
        except Exception as exc:  # noqa: BLE001 — 要的就是把它们记下来断言为空
            crashes.append(repr(exc))

    threads = [threading.Thread(target=go, args=(f"run-{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return opened, errors, crashes


def _open_rows(partition: str) -> list[BrowserSession]:
    with SessionLocal() as db:
        return list(
            db.scalars(select(BrowserSession).where(BrowserSession.partition == partition, BrowserSession.status == "open"))
        )


def test_同一拍打开同一个具名会话_只开出一个_后到的报被占用() -> None:
    ws = _ws()
    rounds = _open_concurrently(
        lambda db, owner, n: browser.open_session(
            db, workspace_id=ws, kind="named", name=f"xhs-{n}", owner_kind="workflow", owner_id=owner, actor=None
        ),
    )
    for n, (opened, errors, crashes) in enumerate(rounds):
        assert crashes == [] and len(opened) == 1 and errors == ["browserErr_sessionBusy"], (n, opened, errors, crashes)
        assert [row.id for row in _open_rows(browser.named_partition(ws, f"xhs-{n}"))] == opened


def test_同一拍打开同一个池档案_只开出一个_后到的报被占用() -> None:
    ws = _ws()
    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == "tester").one()
        profile = browser.create_profile(db, workspace_id=ws, name="号", owner=owner)
        db.commit()
        profile_id, partition, owner_id = profile.id, profile.partition, owner.id

    def open_then_note(db, run, _n):
        return browser.open_session(
            db, workspace_id=ws, profile_id=profile_id, owner_kind="workflow", owner_id=run, actor=owner_id
        )

    for n in range(ROUNDS):
        [(opened, errors, crashes)] = _open_concurrently(open_then_note, rounds=1)
        assert crashes == [] and len(opened) == 1 and errors == ["browserErr_profileBusy"], (n, opened, errors, crashes)
        assert [row.id for row in _open_rows(partition)] == opened
        with SessionLocal() as db:
            browser.close_session(db, opened[0])  # 下一轮重新抢


def test_同一个owner同一拍打开两次_拿到的是同一个会话() -> None:
    ws = _ws()
    rounds = _open_concurrently(
        lambda db, _owner, n: browser.open_session(
            db, workspace_id=ws, kind="named", name=f"xhs-{n}", owner_kind="workflow", owner_id="run-1", actor=None
        ),
    )
    for opened, errors, crashes in rounds:
        assert crashes == [] and errors == [] and len(opened) == 2 and len(set(opened)) == 1


def _hold_write_lock(seconds: float) -> threading.Thread:
    """另一个连接拿着写锁 `seconds` 秒(满负载下别的写事务就是这样把库占住的)。"""
    started = threading.Event()

    def hold() -> None:
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
            started.set()
            time.sleep(seconds)
            conn.rollback()

    thread = threading.Thread(target=hold)
    thread.start()
    started.wait(timeout=5)
    return thread


def test_库被别的写事务占着一会儿_打开会话等它放手_不报database_is_locked() -> None:
    ws = _ws()
    holder = _hold_write_lock(1.0)
    with SessionLocal() as db:
        session = browser.open_session(
            db, workspace_id=ws, kind="named", name="xhs", owner_kind="workflow", owner_id="run-1", actor=None
        )
    holder.join()
    assert [row.id for row in _open_rows(browser.named_partition(ws, "xhs"))] == [session.id]


def test_库一直被占着_重试完按被占用报_不是sqlite的错(monkeypatch) -> None:
    ws = _ws()
    monkeypatch.setattr(browser, "LEASE_ATTEMPTS", 1)
    holder = _hold_write_lock(6.5)  # 比 busy_timeout(5 秒)长
    try:
        with SessionLocal() as db, pytest.raises(browser.BrowserDomainError) as caught:
            browser.open_session(
                db, workspace_id=ws, kind="named", name="xhs", owner_kind="workflow", owner_id="run-1", actor=None
            )
        assert caught.value.key == "browserErr_sessionBusy"
    finally:
        holder.join()


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
