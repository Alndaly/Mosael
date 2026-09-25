"""跑过的迁移记账,下次启动跳过。

五十几个迁移此前每次启动全跑一遍,靠各自幂等兜着 —— 对,但代价随数据量长:十四个会整表读
(每条工作流的图、每张画板的画布)。实测空库 0.07s,两千工作流 + 一千画板 + 五千消息之后 0.40s,
而它们什么都不会做。

这里钉的是记账本身的几条不变式,因为记错的代价是**静默的**:多记一步 = 那个迁移再也不跑
(老库永远升不上来);少记 = 白跑,只是慢。所以三条都要:跑过的记上、失败的不记、对账型的不记。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.db import engine
from app.db.migration_runner import MigrationFailed, MigrationPhase, MigrationPlan, MigrationStep
from tests.util import fresh_client


def _applied() -> set[str]:
    with engine.begin() as conn:
        return {row[0] for row in conn.execute(text("SELECT name FROM schema_migrations"))}


def _step(name: str, operation, *, once: bool = True) -> MigrationStep:
    return MigrationStep(name, MigrationPhase.AFTER_SCHEMA, operation, once=once)


def test_跑过的一次性迁移不再跑第二遍() -> None:
    fresh_client()
    runs = []
    plan = MigrationPlan((_step("t-once", lambda: runs.append(1)),))
    plan.run()
    plan.run()
    plan.run()
    assert runs == [1], "一次性迁移只该跑一次"
    assert "t-once" in _applied()


def test_失败的不记账_下次启动照样重来() -> None:
    """记了就再也不会重试 —— 而一个迁移失败往往是环境问题(盘满、文件占用),下次就好了。"""
    fresh_client()
    attempts = []

    def flaky() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("第一次失败")

    plan = MigrationPlan((_step("t-flaky", flaky),))
    with pytest.raises(MigrationFailed):
        plan.run()
    assert "t-flaky" not in _applied()
    plan.run()
    assert attempts == [1, 1] and "t-flaky" in _applied()


def test_对账型的每次都跑_而且不进记账表() -> None:
    fresh_client()
    runs = []
    plan = MigrationPlan((_step("t-recurring", lambda: runs.append(1), once=False),))
    plan.run()
    plan.run()
    assert runs == [1, 1]
    assert "t-recurring" not in _applied()


def test_真实计划里_只有对账那几步是每次都跑的() -> None:
    """**create_all 必须每次跑**:记账跳过它,新版本加的表就再也建不出来 —— 而表缺了不会在启动时
    报错,要等第一次查询才炸。另外两条处理的东西会不断再产生(孤儿共享、job 的消息键)。
    托管 venv 那条对的是随包解释器的次版本 —— 每次随包解释器换次版本,都会再出现一批。
    随包插件那条对的是这一版带的插件(见 domain/plugins/bundled)—— 每个版本都可能变。"""
    from app.db.migrations import migration_plan

    recurring = {step.name for step in migration_plan().steps if not step.once}
    assert recurring == {
        "create-current-schema", "cleanup-orphan-resource-shares", "migrate-job-keys-are-keys",
        "drop-venvs-built-on-another-python", "install-bundled-plugins",
    }


def test_升级已有库时_一次性迁移仍然会跑一遍() -> None:
    """记账表是这次才有的,老库里没有 —— 所以升级后的第一次启动必须把它们全跑一遍再记上。"""
    from app.db.migrations import migration_plan

    fresh_client()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM schema_migrations"))
    assert _applied() == set()
    migration_plan().run()
    applied = _applied()
    assert len(applied) > 50
    assert "create-current-schema" not in applied, "对账型的不记账"
