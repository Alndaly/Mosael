from __future__ import annotations

from app.db.migration_runner import MigrationPhase
from app.db.migrations import migration_plan


def test_startup_migration_plan_has_one_explicit_schema_boundary() -> None:
    plan = migration_plan()

    schema_steps = [step for step in plan.steps if step.phase is MigrationPhase.SCHEMA]

    assert [step.name for step in schema_steps] == ["create-current-schema"]
    assert plan.steps[-1].phase is MigrationPhase.FILESYSTEM


def test_startup_migration_names_are_stable_and_descriptive() -> None:
    names = [step.name for step in migration_plan().steps]

    assert all(name and "_" not in name for name in names)
    assert names == list(dict.fromkeys(names))
