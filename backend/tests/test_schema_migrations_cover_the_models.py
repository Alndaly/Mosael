"""模型上加了列,就得有迁移把它加到**已存在的库**上。

支持窗口从 v2.1.0 开始(最新 Release 往前 8 个版本)。`schema_baseline.json` 是这一版
真实启动后的 schema,不再记录每张表的出生形状。升级测试照它建库、跑当前迁移计划,再对照模型:
窗口内的真实用户都能到达当前形状。

`create_all` 只建缺失的**表**,从不给已存在的表加列。于是「模型加一列」在新装的机器上一切正常,
在升级的机器上后端**起不来**:

    sqlite3.OperationalError: table provider_credentials has no column named model_catalog
    sqlite3.OperationalError: no such column: jobs.created_by

这两条都是真实撞到的,而且都是同一个疏忽:写了模型,没写迁移。它不该靠人发现 —— 发现它的地方
是用户的启动日志。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import pathlib
import sqlite3

from sqlalchemy import JSON

from app.db.models import Base

BASELINE = pathlib.Path(__file__).parent / "schema_baseline.json"


def _baseline() -> dict[str, list[str]]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


#: 由迁移直接管理、故意不进 Base.metadata 的内部表:迁移账本和「一轮进行中的步骤」。
INTERNAL_TABLES = frozenset({"schema_migrations", "agent_turn_events"})


def test_离开模型的表_升级之后真的没了() -> None:
    """基线描述的是**老库**,而老库里确实有那些后来被删掉的表 —— 所以判据不是"基线里不许
    有模型外的表",而是**它们升级之后必须真的被删掉**。

    此前这条写成「基线里的表都还在模型里」:删一张表就得把它从基线里抹掉,于是删表那条迁移
    在种子库上永远走 no-op 分支(表压根不在)—— 它从没在有数据的库上真跑过。而按结果判还能
    抓住另一种错:模型里删了、却没写 drop 迁移,老用户的库里**永远**留着一张没人认的表。
    """
    from app.core.config import settings
    from app.db.migrations import init_db
    from tests.util import fresh_client

    gone = sorted(
        set(_baseline()) - {table.name for table in Base.metadata.sorted_tables} - INTERNAL_TABLES
    )
    if not gone:
        return
    fresh_client()
    _build_baseline_database(settings.db_path, seeded=True)
    init_db()
    with sqlite3.connect(settings.db_path) as connection:
        present = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
    lingering = sorted(set(gone) & present)
    assert not lingering, (
        "这些表已经离开了模型,而升级之后它们还在老库里 —— 没有迁移删它们:\n  "
        + "\n  ".join(lingering)
        + "\n给每张补一条 DROP TABLE 迁移(参考 migrations._drop_reviews_table)。"
    )


#: 一列该塞什么。按**名字**猜,不按类型 —— 目标不是造一份真实数据,是让每条迁移的
#: 「有东西要搬」那条分支真的跑起来。
_JSON_COLUMNS = frozenset({
    "graph", "canvas", "payload", "config", "args", "result", "content", "snapshot", "units",
    "raw_usage", "effects", "transform", "media_info", "answers", "questions", "state", "secrets",
    "oauth_credential", "model_catalog", "capabilities", "sources", "topics", "tags", "output",
    "input", "discovered_tools", "summary_params", "decision_detail", "body_document", "anchor",
    "plan", "auto_allow_tools", "kinds",
    # 连接和模型行上的两列 JSON:此前没有迁移用 ORM 读这两张表,塞个空串也没人发现;补参考价的迁移要读。
    "extra", "capability_ids",
}) | frozenset(
    column.name for table in Base.metadata.sorted_tables for column in table.columns if isinstance(column.type, JSON)
)


def _seed_value(column: str) -> str:
    if column == "id" or column.endswith("_id"):
        return f"seed-{column}"
    if column.endswith("_at"):
        return "2026-01-01 00:00:00"
    return "{}" if column in _JSON_COLUMNS else ""


def _build_baseline_database(database: pathlib.Path, *, seeded: bool) -> None:
    """推倒当前 schema,只按基线建表 —— `seeded` 时每张表塞一行。

    列一律 TEXT:迁移看的是**列在不在**,不是类型;`id` 给主键,否则引用它的外键在 SQLite 上
    会 `foreign key mismatch`。
    """
    baseline = _baseline()
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
            if not seeded:
                continue
            names = ", ".join(f'"{one}"' for one in columns)
            marks = ", ".join("?" for _ in columns)
            connection.execute(
                f'INSERT INTO "{table}" ({names}) VALUES ({marks})',
                [_seed_value(one) for one in columns],
            )
        connection.execute("PRAGMA user_version = 0")


def test_从基线那一代的库升上来_模型要的每一列都在() -> None:
    """照基线建库 → 跑真迁移 → 对模型。判据不认识 SQL 的写法,只认识结果。"""
    from app.core.config import settings
    from app.db.migrations import init_db
    from tests.util import fresh_client

    fresh_client()  # 让 settings 指向一次性数据目录(它自己会拒绝真实数据目录)
    database = settings.db_path
    _build_baseline_database(database, seeded=False)

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


def test_保留迁移都在最早支持版本的库上跑过() -> None:
    """v1.9.11 的库跑完当前计划后,模型要的列都在,数据分支真的走过,重跑不再改变结果。"""
    from app.core.config import settings
    from app.db.migrations import init_db
    from tests.util import fresh_client

    fresh_client()
    database = settings.db_path
    _build_baseline_database(database, seeded=True)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE workflows SET graph = ? WHERE id = 'seed-id'",
            (json.dumps({"nodes": [{"id": "publish-1", "type": "publish", "config": {}}], "edges": []}),),
        )

    init_db()

    def scalar(sql: str) -> object:
        with sqlite3.connect(database) as connection:
            return connection.execute(sql).fetchone()[0]

    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        columns = {table: {row[1] for row in connection.execute(f'pragma table_info("{table}")')} for table in (
            "publish_tasks", "browser_profiles", "agent_questions", "tool_confirmations", "deployment_config",
        )}
        task = connection.execute(
            "select content_kind, asset_ids from publish_tasks where id = 'seed-id'"
        ).fetchone()
        graph = json.loads(connection.execute("select graph from workflows where id = 'seed-id'").fetchone()[0])
        indexes = {row[0] for row in connection.execute("select name from sqlite_master where type='index'")}

    assert "identity" in columns["browser_profiles"]
    assert "feishu_message_id" in columns["agent_questions"]
    assert "feishu_message_id" in columns["tool_confirmations"]
    assert "update_feed_url" in columns["deployment_config"]
    assert "uq_tool_confirmations_session_tool_call" in indexes
    assert task == ("video", '["seed-asset_id"]'), "发布任务没有改成唯一的内容形状"
    assert graph["nodes"][0]["config"]["content_kind"] == "video", "工作流发布节点没有补上内容形状"

    before = (task, graph, sorted(tables), sorted(indexes))
    init_db()
    with sqlite3.connect(database) as connection:
        task_again = connection.execute(
            "select content_kind, asset_ids from publish_tasks where id = 'seed-id'"
        ).fetchone()
        graph_again = json.loads(connection.execute("select graph from workflows where id = 'seed-id'").fetchone()[0])
        tables_again = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
        indexes_again = {row[0] for row in connection.execute("select name from sqlite_master where type='index'")}
    assert (task_again, graph_again, sorted(tables_again), sorted(indexes_again)) == before
