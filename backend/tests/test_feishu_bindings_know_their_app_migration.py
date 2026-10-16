"""`migrate-feishu-bindings-know-their-app`:飞书绑定的键补上「哪台机器人(哪个飞书应用)」这一维。

飞书的 `open_id` **按应用隔离**(官方《用户身份概述》:不要在跨应用的数据通信中使用 open_id)。
键只有 `(workspace_id, open_id)` 时:同一台机器人换过应用之后,旧行的 open_id 永远匹配不上新事件的
`sender_open_id`(机器人回「你还没有绑定」,而设置页照样显示已绑定);同一个人在两个应用里是两行,
取哪一行由存储顺序定 —— 拿 A 的 open_id 用 B 的 token 发,飞书直接拒。

喂它一份**真实的老形状**(两列主键、没有 bot_id/stale_reason,表里已经有几行):看它搬成什么样、
哪些行能**无歧义**归属、哪些只能标成 stale、再跑一次什么都不做。
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_feishu_bindings_know_their_app as migrate
from app.db.models import FeishuBinding
from tests.util import fresh_client

#: 别名字段里的列定义(与 db/model_slices/feishu.FeishuBinding 逐字一致):(类型, NOT NULL, 缺省)。
_WANTED = {
    "bot_id": ("VARCHAR(64)", True, "''"),
    "stale_reason": ("VARCHAR(200)", True, "''"),
}

#: 老行的四个时刻。`created_at` 是**归属判断的依据**,所以造数据时把它们分开写。
_T_ONLY_OLD = "2026-01-02 00:00:00"      # bot_old 之后、bot_new 之前:那一刻只有一台机器人
_T_AMBIGUOUS = "2026-01-04 00:00:00"     # 两台都在了:说不清是哪台
_T_BEFORE_ANY = "2025-12-31 00:00:00"    # 比机器人还早:那台应用已经不在了
_T_REBUILT = "2026-02-15 00:00:00"       # 另一个工作区:机器人是后来才建的


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


def _old_shape() -> dict[str, str]:
    """建真数据,再把 feishu_bindings 削回**老形状**(这一版之前的模型写不出现在这个样子)。

    老形状是两列主键,SQLite 改主键只能重建表,所以这里直接 DROP 再按当年那版 CREATE 一遍 ——
    和迁移面对的老库逐字一致。返回几个 id,给断言用。
    """
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "W2"}).json()["id"]
    me = client.get("/api/auth/me").json()["id"]
    ids = {"ws": workspace, "other": other, "me": me}
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE feishu_bindings"))
        conn.execute(text(
            "CREATE TABLE feishu_bindings ("
            "workspace_id VARCHAR(64) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, "
            "open_id VARCHAR(120) NOT NULL, "
            "user_id VARCHAR(64) NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "created_at DATETIME NOT NULL, "
            "PRIMARY KEY (workspace_id, open_id))"
        ))
        for key, ws, name, app, created in (
            ("bot_old", workspace, "老应用", "cli_old", "2026-01-01 00:00:00"),
            ("bot_new", workspace, "新应用", "cli_new", "2026-01-03 00:00:00"),
            ("bot_rebuilt", other, "重建的应用", "cli_rebuilt", "2026-02-20 00:00:00"),
        ):
            conn.execute(text(
                "INSERT INTO feishu_bots (id, workspace_id, name, app_id, app_secret, capability, enabled, "
                "status, status_detail, created_at, updated_at) "
                "VALUES (:id, :ws, :name, :app, '', 'editor', 1, 'offline', '', :created, :created)"
            ), {"id": key, "ws": ws, "name": name, "app": app, "created": created})
        for ws, open_id, created in (
            (workspace, "ou_same_person_under_old", _T_ONLY_OLD),
            (workspace, "ou_same_person_ambiguous", _T_AMBIGUOUS),
            (workspace, "ou_same_person_under_gone_app", _T_BEFORE_ANY),
            (other, "ou_under_rebuilt_app", _T_REBUILT),
        ):
            conn.execute(text(
                "INSERT INTO feishu_bindings (workspace_id, open_id, user_id, created_at) "
                "VALUES (:ws, :open_id, :user, :created)"
            ), {"ws": ws, "open_id": open_id, "user": me, "created": created})
    engine.dispose()
    return ids


def _rows() -> dict[str, tuple[str, str]]:
    """open_id → (bot_id, stale_reason)。**迁移之后**才读得动(老形状里那两列不在)。"""
    with engine.connect() as conn:
        return {
            row[0]: (row[1], row[2])
            for row in conn.execute(text("SELECT open_id, bot_id, stale_reason FROM feishu_bindings"))
        }


def _count() -> int:
    """老形状里也读得动的那个数。"""
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT COUNT(*) FROM feishu_bindings")).scalar() or 0)


def test_老库的绑定补上应用这一维_能归属的回填_说不清的标stale_再跑一次什么都不做() -> None:
    _old_shape()
    before = _columns()
    assert "bot_id" not in before and "stale_reason" not in before, "老形状里不该已经有这两列"
    assert set(_primary_key()) == {"workspace_id", "open_id"}, "老形状的主键是两列"
    assert _count() == 4, "四行老数据都该在原地"
    migrate()
    engine.dispose()

    columns = _columns()
    for name, wanted in _WANTED.items():
        assert columns.get(name) == wanted, f"{name} 的列定义和模型对不上:{columns.get(name)} != {wanted}"
    assert _primary_key() == ["workspace_id", "bot_id", "open_id"], "键要加上「哪台机器人」这一维"

    rows = _rows()
    #: 那一刻只有老应用在 → 无歧义归属它(同一个人在另一个应用里的那一行各归各的)。
    assert rows["ou_same_person_under_old"] == ("bot_old", "")
    #: 两台都在了 → 说不清是哪台,**不许默默归到当前那台**:留空 + stale。
    assert rows["ou_same_person_ambiguous"] == ("", "unknown-app")
    #: 比任何机器人都早(那台应用已经不在了)→ 同样说不清。
    assert rows["ou_same_person_under_gone_app"] == ("", "unknown-app")
    #: 另一个工作区:机器人是后来才建的,老行不是它建的。
    assert rows["ou_under_rebuilt_app"] == ("", "unknown-app")

    #: 迁移完之后 ORM 读得动这张表(新列、新键都在),而且 stale 的行照旧认得出来。
    with SessionLocal() as db:
        bindings = {row.open_id: row for row in db.scalars(select(FeishuBinding))}
        assert bindings["ou_same_person_under_old"].bot_id == "bot_old"
        assert bindings["ou_same_person_ambiguous"].stale_reason == "unknown-app"

    migrate()  # 再跑一次:判「bot_id 在不在」,不重建、不重复搬
    engine.dispose()
    assert _columns() == columns
    assert _rows() == rows
