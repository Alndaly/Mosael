"""模型上加了列,就得有迁移把它加到**已存在的库**上。

`create_all` 只建缺失的**表**,从不给已存在的表加列。于是「模型加一列」在新装的机器上一切正常,
在升级的机器上后端**起不来**:

    sqlite3.OperationalError: table provider_credentials has no column named model_catalog
    sqlite3.OperationalError: no such column: jobs.created_by

这两条都是真实撞到的,而且都是同一个疏忽:写了模型,没写迁移。它不该靠人发现 —— 发现它的地方
是用户的启动日志。

这条棘轮的规则很简单:**模型里的每一列,要么在下面这份基线里,要么在 db.py 里有一条 ADD COLUMN。**

基线是"这些列本来就在建表语句里"的记录,只在**新建一张表**时才该增补(新表由 create_all 建,
它的列自然都在 CREATE 里)。给一张老表加列却往基线里补一笔 —— 那正是这条棘轮要拦的事,而它是
一个显眼、需要解释的改动,不是随手就过去的。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import pathlib
import re

from app.db.models import Base

BASELINE = pathlib.Path(__file__).parent / "schema_baseline.json"


def _added_by_migrations() -> set[tuple[str, str]]:
    """db.py 里所有 `ALTER TABLE <表> ADD COLUMN <列>`。"""
    source = pathlib.Path("app/db/migrations.py").read_text(encoding="utf-8")
    pattern = re.compile(r"ALTER TABLE\s+(?:\{table\}|(\w+))\s+ADD COLUMN\s+(\w+)", re.IGNORECASE)
    out: set[tuple[str, str]] = set()
    for table, column in pattern.findall(source):
        out.add((table or "*", column))
    return out


def test_every_model_column_is_reachable_on_an_existing_database() -> None:
    baseline: dict[str, list[str]] = json.loads(BASELINE.read_text())
    migrated = _added_by_migrations()
    # 表名写成 f-string 的迁移(按表循环加同一列)记成 ("*", 列名) —— 那种迁移覆盖它循环到的每张表。
    wildcard = {column for table, column in migrated if table == "*"}

    unreachable: list[str] = []
    for table in Base.metadata.sorted_tables:
        known = set(baseline.get(table.name, []))
        if table.name not in baseline:
            continue  # 新表:create_all 会建,列都在 CREATE 里
        for column in table.columns:
            if column.name in known:
                continue
            if (table.name, column.name) in migrated or column.name in wildcard:
                continue
            unreachable.append(f"{table.name}.{column.name}")

    assert not unreachable, (
        "这些列只存在于模型里 —— 新装的机器有,升级的机器没有,后端会起不到一半就炸:\n  "
        + "\n  ".join(sorted(unreachable))
        + "\n给它们在 app/db/migrations.py 里补一条 ADD COLUMN 迁移(参考 _migrate_job_actor)。"
    )


def test_the_baseline_only_lists_tables_that_still_exist() -> None:
    """删表之后基线也该跟着删 —— 留着一张不存在的表,棘轮就在守一个不存在的约定。"""
    baseline = json.loads(BASELINE.read_text())
    live = {table.name for table in Base.metadata.sorted_tables}
    stale = sorted(set(baseline) - live)
    assert not stale, f"基线里这些表已经不在模型里了:{stale}"
