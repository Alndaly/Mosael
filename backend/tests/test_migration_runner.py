from __future__ import annotations

import pytest

from app.db.migration_runner import MigrationFailed, MigrationPhase, MigrationPlan, MigrationStep


def test_plan_runs_steps_in_declared_order() -> None:
    calls: list[str] = []
    plan = MigrationPlan(
        (
            MigrationStep("before", MigrationPhase.BEFORE_SCHEMA, lambda: calls.append("before")),
            MigrationStep("schema", MigrationPhase.SCHEMA, lambda: calls.append("schema")),
            MigrationStep("after", MigrationPhase.AFTER_SCHEMA, lambda: calls.append("after")),
            MigrationStep("files", MigrationPhase.FILESYSTEM, lambda: calls.append("files")),
        )
    )

    plan.run()

    assert calls == ["before", "schema", "after", "files"]


def test_plan_rejects_duplicate_names_and_phase_regressions() -> None:
    def noop() -> None:
        pass

    with pytest.raises(ValueError, match="duplicate migration step"):
        MigrationPlan(
            (
                MigrationStep("same", MigrationPhase.BEFORE_SCHEMA, noop),
                MigrationStep("same", MigrationPhase.SCHEMA, noop),
            )
        )

    with pytest.raises(ValueError, match="phase order"):
        MigrationPlan(
            (
                MigrationStep("after", MigrationPhase.AFTER_SCHEMA, noop),
                MigrationStep("before", MigrationPhase.BEFORE_SCHEMA, noop),
            )
        )


def test_failure_names_the_step_and_stops_the_plan() -> None:
    calls: list[str] = []

    def fail() -> None:
        raise OSError("disk full")

    plan = MigrationPlan(
        (
            MigrationStep("first", MigrationPhase.BEFORE_SCHEMA, lambda: calls.append("first")),
            MigrationStep("broken", MigrationPhase.BEFORE_SCHEMA, fail),
            MigrationStep("never", MigrationPhase.SCHEMA, lambda: calls.append("never")),
        )
    )

    with pytest.raises(MigrationFailed, match="broken") as raised:
        plan.run()

    assert raised.value.step.name == "broken"
    assert isinstance(raised.value.__cause__, OSError)
    assert calls == ["first"]


def test_every_step_sees_the_schema_the_previous_step_left(monkeypatch) -> None:
    """**每一步之前,连接池里都没有记着旧表结构的连接。**

    迁移靠 inspect() 判断「这一列在不在」。连接池里有好几条连接:上一步用其中一条 ALTER 过,下一步
    拿到另一条时它可能还记着 ALTER 之前的样子,于是再 ADD 一次 —— `duplicate column name`,启动
    失败。macOS 上池子往往只复用一条连接撞不到,Linux 上会撞到(CI 里 migrate-permission-modes
    时红时绿就是它)。所以执行器进来先清池、每一步之后再清。
    """
    from app.core import db

    events: list[str] = []
    monkeypatch.setattr(db.engine, "dispose", lambda *a, **k: events.append("dispose"))
    # 名字取唯一的:记账本是真库,同文件别的测试可能已经把同名步骤记成跑过。
    from uuid import uuid4

    tag = uuid4().hex[:8]
    plan = MigrationPlan(
        (
            MigrationStep(f"pool-first-{tag}", MigrationPhase.BEFORE_SCHEMA, lambda: events.append("first")),
            MigrationStep(f"pool-second-{tag}", MigrationPhase.BEFORE_SCHEMA, lambda: events.append("second")),
        )
    )

    plan.run()

    assert events == ["dispose", "first", "dispose", "second", "dispose"]
