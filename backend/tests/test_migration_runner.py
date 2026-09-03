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
