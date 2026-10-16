"""`migrate-feishu-bindings-drop-stale-rows`:上一步留下的**死行**在这里删掉,`bot_id` 变成名正言顺的主键成员。

上一步(`migrate-feishu-bindings-know-their-app`,已合进 main、身体冻着)把「说不清归属」的老行
写成 `bot_id = '' + stale_reason = 'unknown-app'`。那是**为旧数据留的运行时状态**:`open_id` 按飞书
应用隔离,那些行的 open_id 属于**已经不存在的应用**(落库那一刻工作区里一台机器人都没有,或者有
不止一台)—— 它永远匹配不上任何东西,架构上就是死行。所以这一步不搬它们,只删。

判据落在**结果**上:死行没了、`bot_id` `NOT NULL` 且没有 `DEFAULT ''`(空串哨兵随列定义一起消失)、
`stale_reason` 整列不在、主键还是 `(workspace_id, bot_id, open_id)`、`bot_id` 指着 `feishu_bots`
且 `ON DELETE CASCADE`(机器人没了,它的绑定也没了)。再跑一次什么都不做。

这里喂的是**真实的上一版形状**(三列主键 + `bot_id VARCHAR(64) NOT NULL DEFAULT ''` + `stale_reason`,
与那一步的 CREATE 逐字一致),里面装着四类行:能用的、说不清归属的、父行(工作区 / 用户)不在的、
`bot_id` 指着一台已经不在了的机器人的。
"""

from __future__ import annotations

import sqlite3

from sqlalchemy import select, text

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.db.migrations import init_db, migration_plan
from app.db.models import FeishuBinding
from tests.util import fresh_client, second_client

#: 这一步在计划里的名字(函数名去掉前导下划线、下划线换成连字符,见 migrations._steps)。
STEP = "migrate-feishu-bindings-drop-stale-rows"

#: 迁移之后这张表的**每一列**:(类型, NOT NULL, 缺省)。与 db/model_slices/feishu.FeishuBinding 逐字一致。
_WANTED = {
    "workspace_id": ("VARCHAR(64)", True, None),
    "bot_id": ("VARCHAR(64)", True, None),
    "open_id": ("VARCHAR(120)", True, None),
    "user_id": ("VARCHAR(64)", True, None),
    "created_at": ("DATETIME", True, None),
}

#: 留下的那几条。别的都不该在。
_KEPT = {
    ("bot_kept", "ou_zhangsan"),
    ("bot_other", "ou_zhangsan_other_app"),
    ("bot_in_second_workspace", "ou_in_second_workspace"),
}

_T = "2026-01-01 00:00:00"


def _columns() -> dict[str, tuple[str, bool, object]]:
    with engine.connect() as conn:
        return {
            row[1]: (row[2], bool(row[3]), row[4])
            for row in conn.execute(text("PRAGMA table_info(feishu_bindings)"))
        }


def _primary_key() -> list[str]:
    """主键里的列,**按主键序**(PRAGMA 的 pk 那一格是序号,1 开始)。"""
    with engine.connect() as conn:
        rows = [(row[5], row[1]) for row in conn.execute(text("PRAGMA table_info(feishu_bindings)"))]
    return [name for order, name in sorted(rows) if order]


def _foreign_keys() -> set[tuple[str, str, str, str]]:
    """(指向的表, 本表的列, 指向的列, on_delete)。"""
    with engine.connect() as conn:
        return {
            (row[2], row[3], row[4], row[6])
            for row in conn.execute(text("PRAGMA foreign_key_list(feishu_bindings)"))
        }


def _table_sql() -> str:
    with engine.connect() as conn:
        return str(conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'feishu_bindings'")
        ).scalar_one())


def _rows() -> dict[tuple[str, str], tuple[str, str]]:
    """(bot_id, open_id) → (user_id, created_at)。迁移之后才读得动这些列。"""
    with engine.connect() as conn:
        return {
            (row[0], row[1]): (row[2], row[3])
            for row in conn.execute(text("SELECT bot_id, open_id, user_id, created_at FROM feishu_bindings"))
        }


def _bot(conn, bot_id: str, workspace_id: str, name: str) -> None:
    conn.execute(text(
        "INSERT INTO feishu_bots (id, workspace_id, name, app_id, app_secret, capability, enabled, "
        "status, status_detail, created_at, updated_at) "
        "VALUES (:id, :ws, :name, :app, '', 'editor', 1, 'offline', '', :t, :t)"
    ), {"id": bot_id, "ws": workspace_id, "name": name, "app": f"cli_{bot_id}", "t": _T})


def _v30_shape() -> dict[str, str]:
    """建真数据,再把 feishu_bindings 削回**上一步跑完之后**的形状,塞进四类行。

    那个形状是**历史快照**:与 `_migrate_feishu_bindings_know_their_app` 的 CREATE 逐字一致
    (三列主键、`bot_id` 有 `DEFAULT ''`、`stale_reason` 在)。返回几个 id,给断言用。
    """
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    me = client.get("/api/auth/me").json()["id"]
    other_workspace = second_client("lisi").post("/api/workspaces", json={"name": "W2"}).json()["id"]
    other = second_client("lisi").get("/api/auth/me").json()["id"]
    ids = {"ws": workspace, "me": me, "other": other, "other_ws": other_workspace}
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE feishu_bindings"))
        conn.execute(text(
            "CREATE TABLE feishu_bindings ("
            "workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, "
            "bot_id VARCHAR(64) NOT NULL DEFAULT '', "
            "open_id VARCHAR(120) NOT NULL, "
            "user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "stale_reason VARCHAR(200) NOT NULL DEFAULT '', "
            "created_at DATETIME NOT NULL, "
            "PRIMARY KEY (workspace_id, bot_id, open_id))"
        ))
        _bot(conn, "bot_kept", workspace, "留着的")
        _bot(conn, "bot_other", workspace, "另一台")
        _bot(conn, "bot_in_second_workspace", other_workspace, "另一个工作区的")
        rows = (
            #: 能用的两条:同一个人在两台应用里各一行(open_id 按应用隔离)。
            (workspace, "bot_kept", "ou_zhangsan", me, ""),
            (workspace, "bot_other", "ou_zhangsan_other_app", me, ""),
            #: 另一个工作区的绑定:这一步不该动它。
            (other_workspace, "bot_in_second_workspace", "ou_in_second_workspace", other, ""),
            #: 说不清归属的死行:落库那一刻工作区里没有机器人 / 有不止一台。永远匹配不上任何东西。
            (workspace, "", "ou_stale_unknown_app", me, "unknown-app"),
        )
        for ws, bot_id, open_id, user, stale in rows:
            conn.execute(text(
                "INSERT INTO feishu_bindings (workspace_id, bot_id, open_id, user_id, stale_reason, created_at) "
                "VALUES (:ws, :bot, :open_id, :user, :stale, :t)"
            ), {"ws": ws, "bot": bot_id, "open_id": open_id, "user": user, "stale": stale, "t": _T})
    engine.dispose()
    #: 父行(工作区 / 用户)不在的行,以及 bot_id 指着一台已经不在了的机器人的行 —— 外键在这些行落库的年代
    #: 还没在每个连接上开着,这种行真的存在。SQLite 的 `PRAGMA foreign_keys` 在事务里改不动,所以另开一条
    #: 连接、明说关掉它,把老库那份"没有约束的脸"照原样摆出来。
    with sqlite3.connect(settings.db_path) as raw:
        raw.execute("PRAGMA foreign_keys=OFF")
        for ws, bot_id, open_id, user in (
            ("ghost-workspace", "bot_kept", "ou_orphan_workspace", me),
            (workspace, "bot_kept", "ou_orphan_user", "ghost-user"),
            (workspace, "bot_gone", "ou_orphan_bot", me),
        ):
            raw.execute(
                "INSERT INTO feishu_bindings (workspace_id, bot_id, open_id, user_id, stale_reason, created_at) "
                "VALUES (?, ?, ?, ?, '', ?)",
                (ws, bot_id, open_id, user, _T),
            )
    engine.dispose()
    return ids


def _upgraded() -> dict[str, str]:
    """把这份 v30 形状的库交给**真的升级路径**(`init_db`),像维护者机器上那样。

    记账本里先抹掉这一步那一行:真库停在 v30 时它本来就没有(新的一步 = 新的一行账),
    而 `fresh_client()` 是在**这一版**建的空库上跑的,账已经记满了。
    """
    ids = _v30_shape()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM schema_migrations WHERE name = :name"), {"name": STEP})
    #: 这一步要是没跑(计划里没有它、或账没抹掉),下面几条断言看到的就是**原样的 v30 形状**:
    #: 死行还在、stale_reason 还在 —— 每条都会指着那件事说话,不会因为"什么都没跑"而变绿。
    init_db()
    engine.dispose()
    return ids


def _step():
    found = next((step for step in migration_plan().steps if step.name == STEP), None)
    assert found is not None, f"迁移计划里没有这一步:{STEP}"
    return found


def test_说不清归属的老行在迁移里被删掉() -> None:
    """`bot_id=''` 的行属于**已经不存在的应用**,永远匹配不上任何东西 —— 迁移里直接删。

    连同父行(工作区 / 用户)不在的行、`bot_id` 指着已经不在了的机器人的行:它们同样没有任何读者
    (面板按机器人列、认人按机器人查都取不到它们),而新的 `bot_id` 外键要求它们指着一台真机器人。
    这三行是**活的守卫**:不 join 父表直接搬的话,`init_db` 当场撞 `FOREIGN KEY constraint failed`
    (上面那条迁移真踩过),这条用例会以升级失败告终,而不是安静地少搬几行。
    """
    ids = _upgraded()

    rows = _rows()
    assert [key for key in rows if key[0] == ""] == [], (
        "说不清归属的老行还留在表里 —— 它是「设置页说已绑定、机器人说没绑定」那只错觉的源头,"
        "该在迁移里删掉,而不是留成运行时要解释的状态"
    )
    assert set(rows) == _KEPT, f"该留下的绑定被动过了:{sorted(rows)}"
    assert rows[("bot_kept", "ou_zhangsan")] == (ids["me"], _T), (
        "留下的行没有原样搬过来(created_at 是历史,不是迁移那一刻)"
    )


def test_bot_id是名正言顺的主键成员_而stale_reason整列没了() -> None:
    """空串哨兵随列定义一起消失:`bot_id` `NOT NULL`、**没有默认值**;`stale_reason` 不再存在。

    模型那边一起看:库里删了、模型上还留着默认值的话,不写 bot_id 的 insert 又会写出一行空串。
    """
    _upgraded()

    columns = _columns()
    assert "stale_reason" not in columns, "表里还有 stale_reason 这一列 —— 那个概念整个不该存在"
    assert columns == _WANTED, f"列定义和模型对不上:{columns}"
    assert _primary_key() == ["workspace_id", "bot_id", "open_id"], "主键仍应是这三列,顺序不变"

    modelled = FeishuBinding.__table__.c.bot_id
    assert "stale_reason" not in FeishuBinding.__table__.c, "模型上还留着 stale_reason"
    assert modelled.default is None and modelled.server_default is None, (
        "模型上的 bot_id 还带着默认值 —— 空串哨兵会从 insert 那一侧回来"
    )
    with SessionLocal() as db:
        kept = {(row.bot_id, row.open_id) for row in db.scalars(select(FeishuBinding))}
    assert kept == _KEPT


def test_绑定的bot_id指着机器人_机器人没了绑定也没了() -> None:
    """`bot_id` 是外键、`ON DELETE CASCADE`:那一行随机器人一起没有意义(open_id 按应用隔离)。"""
    _upgraded()

    assert ("feishu_bots", "bot_id", "id", "CASCADE") in _foreign_keys(), _foreign_keys()


def test_再跑一次什么都不做() -> None:
    """迁移在真实机器上会被重启反复经过:第二次必须认得出"已经是这个形状了"。"""
    _v30_shape()
    step = _step()
    step.operation()
    engine.dispose()
    once = (_columns(), _primary_key(), _rows(), _table_sql())

    step.operation()
    engine.dispose()
    assert (_columns(), _primary_key(), _rows(), _table_sql()) == once, "再跑一次改变了结果(重建 / 重复搬)"
