"""模型上加了列,就得有迁移把它加到**已存在的库**上。

`create_all` 只建缺失的**表**,从不给已存在的表加列。于是「模型加一列」在新装的机器上一切正常,
在升级的机器上后端**起不来**:

    sqlite3.OperationalError: table provider_credentials has no column named model_catalog
    sqlite3.OperationalError: no such column: jobs.created_by

这两条都是真实撞到的,而且都是同一个疏忽:写了模型,没写迁移。它不该靠人发现 —— 发现它的地方
是用户的启动日志。

**这条棘轮此前问的是一个代理问题。** 它在 `migrations.py` 的源码里正则找
`ALTER TABLE <表> ADD COLUMN <列>`,找到就算「到得了」。三个洞:

· 表名不在基线里就 `continue` —— 整张表跳过。17 张表(notes、reviews、boards、comments、
  scenes_3d……)因此从来没被查过,其中 6 张早就有 ADD COLUMN 迁移,证明「新表的列都在 CREATE 里」
  这个豁免理由对它们已经不成立;
· `ALTER TABLE scene_3d_models ADD COLUMN {name}`(循环里加两列)那一句,`(\\w+)` 匹配不到
  `{name}`,于是 file_key/size 在它眼里不存在;
· SQLite 改主键只能**重建表**(`CREATE TABLE …_new` + `RENAME`),而重建整个不是 ADD COLUMN。

所以现在不问代理问题了:**照基线建一个老库,把全套迁移真的跑一遍,再看模型要的列是不是都在。**
这条判据与迁移怎么写无关 —— ALTER、循环 ALTER、重建表、改主键,一视同仁。

它当场抓到两件真事:

1. `_migrate_deployment_admin`(加 `users.is_deployment_admin`)排在**三条读这一列的迁移之后**,
   老库启动直接炸在 `no such column: is_deployment_admin`;
2. `provider_credentials` 的基线只记了 3 列,而这张表出生时就有 9 列 —— 基线本身是错的。

基线是「这张表出生时 CREATE 里有哪些列」的记录。往里补一笔的场合只有一个:**新建一张表**。
给一张老表加列却往基线里补一笔,那正是这条棘轮要拦的事,而它是一个显眼、需要解释的改动。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import pathlib
import sqlite3

from app.db.models import Base

BASELINE = pathlib.Path(__file__).parent / "schema_baseline.json"


def _baseline() -> dict[str, list[str]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_基线覆盖模型里的每一张表() -> None:
    """漏一张表,上一版就整张跳过 —— 而跳过是静默的,看起来和通过一模一样。"""
    absent = sorted({table.name for table in Base.metadata.sorted_tables} - set(_baseline()))
    assert not absent, (
        "这些表不在 tests/schema_baseline.json 里:\n  "
        + "\n  ".join(absent)
        + "\n新建的表请把它**出生时 CREATE 里的列**记进去(不是今天模型上的全部列——"
        "后来加的列应该由迁移到达)。"
    )


def test_the_baseline_only_lists_tables_that_still_exist() -> None:
    """删表之后基线也该跟着删 —— 留着一张不存在的表,棘轮就在守一个不存在的约定。"""
    live = {table.name for table in Base.metadata.sorted_tables}
    stale = sorted(set(_baseline()) - live)
    assert not stale, f"基线里这些表已经不在模型里了:{stale}"


def test_从基线那一代的库升上来_模型要的每一列都在() -> None:
    """照基线建库 → 跑真迁移 → 对模型。判据不认识 SQL 的写法,只认识结果。"""
    from app.core.config import settings
    from app.db.migrations import init_db
    from tests.util import fresh_client

    fresh_client()  # 让 settings 指向一次性数据目录(它自己会拒绝真实数据目录)
    database = settings.db_path
    baseline = _baseline()

    # 推倒当前 schema,只按基线建表。列一律 TEXT:迁移看的是**列在不在**,不是类型;
    # `id` 给主键,否则引用它的外键在 SQLite 上会 `foreign key mismatch`。
    with sqlite3.connect(database) as connection:
        existing = connection.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        ).fetchall()
        for (name,) in existing:
            connection.execute(f'DROP TABLE IF EXISTS "{name}"')
        for table, columns in baseline.items():
            declared = ", ".join(
                f'"{one}" TEXT' + (" PRIMARY KEY" if one == "id" else "") for one in columns
            )
            connection.execute(f'CREATE TABLE "{table}" ({declared})')
        connection.execute("PRAGMA user_version = 0")

    init_db()

    unreachable: list[str] = []
    with sqlite3.connect(database) as connection:
        live = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        for table in Base.metadata.sorted_tables:
            if table.name not in live:
                unreachable.append(f"{table.name}(整张表)")
                continue
            present = {row[1] for row in connection.execute(f'PRAGMA table_info("{table.name}")')}
            unreachable.extend(
                f"{table.name}.{column.name}" for column in table.columns if column.name not in present
            )

    assert not unreachable, (
        "从基线那一代的库升上来之后,这些东西不存在 —— 新装的机器有,升级的机器没有,"
        "后端会起不到一半就炸:\n  "
        + "\n  ".join(sorted(unreachable))
        + "\n在 app/db/migrations.py 里补一条迁移(参考 _migrate_job_actor),"
        "并确认它在计划里排在**读这一列的迁移之前**。"
    )
