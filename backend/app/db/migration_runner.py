"""Small, explicit runner for ordered startup migrations.

Migration operations own their transaction boundaries because SQLite schema changes and data
backfills do not share one useful all-or-nothing transaction.  The runner owns the concerns that
are common to every operation: stable names, phase ordering, timing, and actionable failures.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import IntEnum
from time import perf_counter

logger = logging.getLogger(__name__)

MigrationOperation = Callable[[], None]


class MigrationPhase(IntEnum):
    """The only legal ordering of startup migration work."""

    BEFORE_SCHEMA = 1
    SCHEMA = 2
    AFTER_SCHEMA = 3
    FILESYSTEM = 4


@dataclass(frozen=True)
class MigrationStep:
    name: str
    phase: MigrationPhase
    operation: MigrationOperation


class MigrationFailed(RuntimeError):
    """Add the stable migration identity while preserving the original exception as the cause."""

    def __init__(self, step: MigrationStep) -> None:
        self.step = step
        super().__init__(f"migration '{step.name}' failed during {step.phase.name.lower()}")


@dataclass(frozen=True)
class MigrationPlan:
    steps: tuple[MigrationStep, ...]

    def __init__(self, steps: Iterable[MigrationStep]) -> None:
        materialized = tuple(steps)
        object.__setattr__(self, "steps", materialized)
        self._validate()

    def _validate(self) -> None:
        names: set[str] = set()
        previous: MigrationPhase | None = None
        for step in self.steps:
            if not step.name:
                raise ValueError("migration step name must not be empty")
            if step.name in names:
                raise ValueError(f"duplicate migration step: {step.name}")
            if previous is not None and step.phase < previous:
                raise ValueError(
                    f"migration phase order regressed from {previous.name} to {step.phase.name} at {step.name}"
                )
            names.add(step.name)
            previous = step.phase

    def run(self) -> None:
        for step in self.steps:
            started = perf_counter()
            logger.debug("running migration %s (%s)", step.name, step.phase.name.lower())
            try:
                step.operation()
            except Exception as error:
                logger.exception("migration %s failed (%s)", step.name, step.phase.name.lower())
                raise MigrationFailed(step) from error
            logger.debug("migration %s completed in %.3fs", step.name, perf_counter() - started)
