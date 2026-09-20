"""Small, explicit runner for ordered startup migrations.

Migration operations own their transaction boundaries because SQLite schema changes and data
backfills do not share one useful all-or-nothing transaction.  The runner owns the concerns that
are common to every operation: stable names, phase ordering, timing, actionable failures, and
**记住哪些已经跑过了**。

记账之前,五十几个迁移每次启动全跑一遍,靠各自幂等兜着。那是对的,但代价随数据量长:
十四个迁移会整表读一遍(每条工作流的图、每张画板的画布)。实测空库 0.07s,
两千工作流 + 一千画板 + 五千消息之后 0.40s —— 再大十倍就是每次启动四秒,而它们什么都不会做。

所以一次性的迁移跑成功就记进 `schema_migrations`,下次直接跳过;**少数几个是「对账」而不是
「迁移」**(清孤儿共享、把 job 的消息键归一、建当前 schema),它们声明成 recurring,照旧每次跑。

失败的不记账 —— 下次启动照样重来,这正是想要的。
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
    #: False = 这一步是**对账**,不是一次性迁移:每次启动都要跑,不记账也不跳过。
    once: bool = True


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
        ledger = _Ledger()
        applied = ledger.applied()
        skipped = 0
        for step in self.steps:
            if step.once and step.name in applied:
                skipped += 1
                continue
            started = perf_counter()
            logger.debug("running migration %s (%s)", step.name, step.phase.name.lower())
            try:
                step.operation()
            except Exception as error:
                logger.exception("migration %s failed (%s)", step.name, step.phase.name.lower())
                raise MigrationFailed(step) from error
            if step.once:
                # 记账在**成功之后**:失败的下次启动照样重来。
                ledger.record(step.name)
            logger.debug("migration %s completed in %.3fs", step.name, perf_counter() - started)
        if skipped:
            logger.debug("skipped %d migration(s) already recorded as applied", skipped)


class _Ledger:
    """哪些迁移已经跑过了。**不经 ORM** —— 它比模型层更早,建表那一步还没跑。"""

    TABLE = "schema_migrations"

    def __init__(self) -> None:
        from sqlalchemy import text

        from app.core.db import engine

        self._engine = engine
        self._text = text
        with engine.begin() as conn:
            conn.execute(text(
                f"CREATE TABLE IF NOT EXISTS {self.TABLE} ("
                "name VARCHAR(120) PRIMARY KEY, applied_at VARCHAR(32) NOT NULL)"
            ))

    def applied(self) -> set[str]:
        with self._engine.begin() as conn:
            return {row[0] for row in conn.execute(self._text(f"SELECT name FROM {self.TABLE}"))}

    def record(self, name: str) -> None:
        #: 时间戳用**和全库同一个来源**(model_base.now),不自己再造一份 —— 两种时间语义混在
        #: 一张库里,以后排查「这步什么时候跑的」会对不上别的表。存成字符串是因为 sqlite3 的
        #: datetime 适配器在 3.12 起已废弃,而这张表没有任何代码需要把它读回成 datetime。
        from app.db.model_base import now

        with self._engine.begin() as conn:
            conn.execute(
                self._text(f"INSERT OR REPLACE INTO {self.TABLE} (name, applied_at) VALUES (:name, :at)"),
                {"name": name, "at": now().isoformat(sep=" ", timespec="seconds")},
            )
