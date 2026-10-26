"""一次用例一个事务(core/unit_of_work、api/deps.transaction)的行为。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.api.deps import Tx
from app.core.db import engine
from app.core.unit_of_work import after_commit, unit_of_work
from tests.util import fresh_client


@pytest.fixture()
def probe():
    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS uow_probe (v TEXT)"))
        conn.execute(text("DELETE FROM uow_probe"))
    yield lambda: [row[0] for row in engine.connect().execute(text("SELECT v FROM uow_probe ORDER BY v"))]
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS uow_probe"))


def _write(db: Session, value: str) -> None:
    db.execute(text("INSERT INTO uow_probe (v) VALUES (:v)"), {"v": value})


def test_a_use_case_commits_once_at_the_end(probe) -> None:
    with unit_of_work() as db:
        _write(db, "a")
        _write(db, "b")
    assert probe() == ["a", "b"]


def test_a_failure_halfway_leaves_nothing_behind(probe) -> None:
    """这正是领域函数中途提交留下的「半截状态」:前半段落了库,后半段没有。"""
    with pytest.raises(RuntimeError), unit_of_work() as db:
        _write(db, "a")
        raise RuntimeError("second half failed")
    assert probe() == []


def test_after_commit_runs_only_once_committed(probe) -> None:
    seen: list[list[str]] = []
    with unit_of_work() as db:
        _write(db, "a")
        after_commit(db, lambda: seen.append(probe()))
        assert seen == [], "提交之前不跑"
    assert seen == [["a"]], "跑的时候看得见刚提交的行"

    dropped: list[str] = []
    with pytest.raises(RuntimeError), unit_of_work() as db:
        after_commit(db, lambda: dropped.append("ran"))
        raise RuntimeError
    assert dropped == [], "回滚了就不跑"


def test_after_commit_also_fires_on_a_legacy_commit(probe) -> None:
    """迁移期:还没改的代码自己 commit,登记的钩子同样要跑。"""
    from app.core.db import SessionLocal

    seen: list[str] = []
    with SessionLocal() as db:
        _write(db, "a")
        after_commit(db, lambda: seen.append("ran"))
        db.commit()
    assert seen == ["ran"]


def test_回滚到保存点_里面登记的钩子不跑_外面的照跑(probe) -> None:
    """保存点里登记的钩子(删文件、起线程)跟着保存点一起撤:行回来了,文件不能没。外层的不受牵连 —— 此前清钩子
    挂在 `after_rollback` 上,SQLAlchemy 回滚保存点也发它,一次被接住的保存点回滚把外层的钩子也清光了。"""
    seen: list[str] = []
    with unit_of_work() as db:
        _write(db, "outer")
        after_commit(db, lambda: seen.append("outer"))
        with pytest.raises(RuntimeError), db.begin_nested():
            _write(db, "inner-undone")
            after_commit(db, lambda: seen.append("inner-undone"))
            raise RuntimeError
        with db.begin_nested():
            _write(db, "inner-kept")
            after_commit(db, lambda: seen.append("inner-kept"))
    assert probe() == ["inner-kept", "outer"]
    assert seen == ["outer", "inner-kept"]


def test_释放保存点不是提交_钩子等到最外层提交(probe) -> None:
    """保存点释放也会发 after_commit(SQLAlchemy 对**每一层** commit 都发),但释放不等于落库:
    外层之后照样可能回滚。此前 `_run_hooks` 不分辨层级,一次 `begin_nested()` 的正常结束就把
    **所有**钩子(包括外层的)取走跑掉了 —— 外层一失败,文件已经删了、线程已经起了,行却回来了。

    所以:保存点释放一拍都不跑;外层提交之后按登记顺序各跑一次;外层回滚则全部丢掉。"""
    seen: list[str] = []
    with pytest.raises(RuntimeError), unit_of_work() as db:
        _write(db, "outer")
        after_commit(db, lambda: seen.append("outer"))
        with db.begin_nested():
            _write(db, "inner-undone")
            after_commit(db, lambda: seen.append("inner-undone"))
        assert seen == [], "保存点释放不是提交,钩子不该跑"
        raise RuntimeError("外层失败")
    assert seen == [], "外层回滚了,保存点里登记的钩子跟着丢掉"
    assert probe() == []

    with unit_of_work() as db:
        _write(db, "a")
        with db.begin_nested():
            after_commit(db, lambda: seen.append("inner"))
        after_commit(db, lambda: seen.append("outer"))
        assert seen == [], "外层还没提交"
    assert seen == ["inner", "outer"], "只有最外层提交之后才跑,且每条只跑一次"
    assert probe() == ["a"]


def test_保存点是事务里的第一句时_外层回滚照样收回它(probe) -> None:
    """pysqlite 只在第一句写之前自己 BEGIN,SAVEPOINT 不算写。此前事务里还没写过时开保存点,SQLite 把它当成最外层
    事务的开头,RELEASE 当场提交 —— 外层之后回滚,保存点里写的收不回来。现在这种保存点开在一个 `BEGIN IMMEDIATE`
    里(core/db),从来不是最外层:释放它只是并进外层,外层回滚一起撤。"""
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        with db.begin_nested():
            _write(db, "released")
        db.rollback()
    assert probe() == []


def _app() -> FastAPI:
    app = FastAPI()

    @app.post("/ok")
    def ok(db: Tx) -> dict:
        _write(db, "ok")
        return {"done": True}

    @app.post("/refuse")
    def refuse(db: Tx) -> dict:
        _write(db, "refused")
        raise HTTPException(status_code=409, detail="no")

    @app.post("/commit-fails")
    def commit_fails(db: Tx) -> dict:
        _write(db, "lost")

        def boom(session, *_args):
            raise RuntimeError("disk full")

        event.listen(db, "before_commit", boom)
        return {"done": True}

    return app


def test_the_route_transaction_commits_on_success_and_rolls_back_on_http_errors(probe) -> None:
    client = TestClient(_app())
    assert client.post("/ok").status_code == 200
    assert client.post("/refuse").status_code == 409
    assert probe() == ["ok"], "HTTPException 也要回滚 —— 拒绝的请求不该留下写了一半的东西"


def test_a_failed_commit_is_this_requests_500_not_a_silent_success(probe) -> None:
    """收尾在响应发出之前执行:提交失败的请求不能已经回了 200。"""
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.post("/commit-fails").status_code == 500
    assert probe() == []
