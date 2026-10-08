"""写的时候碰上别人攥着写锁:排队等,不当场失败;等满了还没等到,失败里说得出是谁攥着(core/db)。

集成跑全量时,评论区洞察那条工作流的「存成笔记」偶尔报 database is locked(INSERT INTO notes)。当时的猜测是
节点会话先读后写、快照过期 —— SQLite 对这种升级不排队,当场失败。量下来不是:pysqlite 只在第一句写之前才 BEGIN,
节点会话里的读各自自动提交,第一句写时手上没有读事务,碰上别人攥锁就按 busy_timeout 排队。那次失败只能是
**等满了上限**(当时 5 秒)—— 有人攥写锁攥得比它久。这里钉住:

- 节点读过、别人随后提交了一笔,节点照样写得进去(不是快照过期);
- 节点写的时候别人攥着锁,它排队等,放手之后写进去;
- 攥得比上限还久时,节点等满了才失败,失败(和日志)里点名攥锁的线程和它的第一句写 —— 那次没留下这句话,所以查不到是谁;
- 事务里第一句就是保存点、保存点里先读后写:此前这是真会当场失败的那一种,现在先拿锁、排队等;
- 攥写锁超过 LONG_WRITE_SECONDS 的事务,放手时记一条警告,说清从哪一行开始写的。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError

from app.core import db as core_db
from app.core.db import SessionLocal, engine
from app.core.unit_of_work import unit_of_work
from app.db.models import Note, Workflow, Workspace
from app.domain.workflows import executors as registry
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client, lock_wait

GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "save", "type": "note_create", "config": {"title": "评论区洞察", "markdown": "大家最关心显不显黑"}},
    ],
    "edges": [{"source": "start", "target": "save"}],
}


def _workflow() -> tuple[str, str]:
    """(工作区, 工作流)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=ws, name="存笔记", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        return ws, workflow.id


def _notes(ws: str) -> int:
    with SessionLocal() as db:
        return db.query(Note).filter(Note.workspace_id == ws).count()


class _Holder:
    """另一条连接攥着写锁,直到测试 `release()`。`ws` 给了就用一句 UPDATE 拿锁(像一个普通的写事务那样),
    否则 `BEGIN IMMEDIATE`。"""

    def __init__(self, *, ws: str | None = None, name: str = "攥锁的线程") -> None:
        self._release = threading.Event()
        holding = threading.Event()

        def hold() -> None:
            with SessionLocal() as db:
                if ws is None:
                    db.connection().exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    db.execute(text("UPDATE workspaces SET name = name WHERE id = :id"), {"id": ws})
                holding.set()
                self._release.wait(60)
                db.rollback()

        self._thread = threading.Thread(target=hold, name=name)
        self._thread.start()
        assert holding.wait(30), "攥锁的连接一直没拿到写锁"

    def release(self) -> None:
        self._release.set()
        self._thread.join(timeout=30)
        assert not self._thread.is_alive()


@contextmanager
def _settled(prefix: str) -> Iterator[tuple[threading.Event, threading.Event]]:
    """(开始执行, 有了结果):`prefix` 开头的那一句开始执行时、执行完或报错时各 set 一个。"""
    started, done = threading.Event(), threading.Event()

    def before(_conn, _cursor, statement, *_args) -> None:
        if statement.lstrip().startswith(prefix):
            started.set()

    def after(_conn, _cursor, statement, *_args) -> None:
        if statement.lstrip().startswith(prefix):
            done.set()

    def failed(context) -> None:
        if (context.statement or "").lstrip().startswith(prefix):
            done.set()

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    event.listen(engine, "handle_error", failed)
    try:
        yield started, done
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)
        event.remove(engine, "handle_error", failed)


def test_节点读过之后别人提交了一笔_节点照样写得进去_不是快照过期(monkeypatch) -> None:
    ws, wf_id = _workflow()
    note_create = registry._REGISTRY["note_create"]

    def read_then_write(db, scope, config):
        db.scalars(select(Workspace)).all()
        with SessionLocal() as other:  # 读完、写之前,另一条连接提交一笔
            other.execute(text("UPDATE workspaces SET name = '改过' WHERE id = :id"), {"id": ws})
            other.commit()
        return note_create(db, scope, config)

    monkeypatch.setitem(registry._REGISTRY, "note_create", read_then_write)
    execute_graph(GRAPH, wf_id=wf_id, params={})
    assert _notes(ws) == 1


def test_节点写笔记时别人攥着写锁_它排队等_放手之后写进去() -> None:
    ws, wf_id = _workflow()
    outcome: dict[str, str] = {}

    def run() -> None:
        try:
            execute_graph(GRAPH, wf_id=wf_id, params={})
            outcome["result"] = "ok"
        except Exception as exc:  # noqa: BLE001 — 断言里说清是什么
            outcome["result"] = repr(exc)[:300]

    holder = _Holder()
    with _settled("INSERT INTO notes") as (started, done):
        runner = threading.Thread(target=run)
        runner.start()
        try:
            assert started.wait(30), "节点一直没走到写笔记那一句"
            assert not done.wait(1.0), f"节点没有排队等写锁,当场就有了结果:{outcome}"
        finally:
            holder.release()
        runner.join(30)
    assert outcome == {"result": "ok"}
    assert _notes(ws) == 1


def test_写锁攥得比等的上限还久_节点等满了才失败_失败里点名攥锁的是谁(caplog) -> None:
    """集成那次的报错原样复现:run_node → note_create → INSERT INTO notes → database is locked。它只在等满上限之后出现。"""
    ws, wf_id = _workflow()
    caplog.set_level(logging.WARNING, logger="app.core.db")
    with lock_wait(0.5):
        holder = _Holder(ws=ws, name="攥着写锁的那个线程")
        try:
            began = time.monotonic()
            with pytest.raises(OperationalError) as caught:
                execute_graph(GRAPH, wf_id=wf_id, params={})
            waited = time.monotonic() - began
        finally:
            holder.release()
    assert "database is locked" in str(caught.value) and "INSERT INTO notes" in str(caught.value)
    assert waited >= 0.5, f"只等了 {waited:.2f} 秒就失败了:不是排队等满,是当场失败"
    said = "\n".join(getattr(caught.value, "__notes__", []))
    assert "等满了" in said, said
    assert "攥着写锁的那个线程" in said and "UPDATE workspaces" in said, said
    assert said in caplog.text, "日志里也要有同一句(真机上看不到异常对象)"
    assert _notes(ws) == 0


def test_保存点开头的事务里先读后写_碰上别人攥着写锁_排队等而不是当场失败() -> None:
    ws, _ = _workflow()
    outcome: dict[str, str] = {}
    entered, finished = threading.Event(), threading.Event()

    def savepoint_read_write() -> None:
        entered.set()
        try:
            with SessionLocal() as db:
                with db.begin_nested():
                    db.scalars(select(Workspace)).all()
                    db.execute(text("UPDATE workspaces SET name = '保存点里改的' WHERE id = :id"), {"id": ws})
                db.commit()
            outcome["result"] = "ok"
        except Exception as exc:  # noqa: BLE001 — 断言里说清是什么
            outcome["result"] = str(exc).splitlines()[0]
        finally:
            finished.set()

    holder = _Holder()
    worker = threading.Thread(target=savepoint_read_write)
    worker.start()
    try:
        assert entered.wait(30)
        assert not finished.wait(1.0), f"没有排队等写锁,当场就有了结果:{outcome}"
    finally:
        holder.release()
    worker.join(30)
    assert outcome == {"result": "ok"}
    with SessionLocal() as db:
        assert db.get(Workspace, ws).name == "保存点里改的"


def test_攥写锁太久的事务_放手时记一条警告_说清从哪一行开始写(monkeypatch, caplog) -> None:
    ws, wf_id = _workflow()
    monkeypatch.setattr(core_db, "LONG_WRITE_SECONDS", 0.0)
    caplog.set_level(logging.WARNING, logger="app.core.db")
    execute_graph(GRAPH, wf_id=wf_id, params={})
    held = [record.getMessage() for record in caplog.records if "写锁攥了" in record.getMessage()]
    assert any("INSERT INTO notes" in line and "domain/notes/__init__.py" in line and "create_note" in line
               for line in held), held
