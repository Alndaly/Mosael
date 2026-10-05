"""素材按名称排序:中文按拼音、和英文按字母混排,数字按大小(规则见 core/collation)。

分页之后排序挪到了服务端,名称排序成了 SQLite 的码位顺序:「阿」排到「草莓」后面、中文名一个个乱跳。分页之前
浏览器里那行 `localeCompare(b, "zh-CN")` 也不理想:汉字整块排在英文前面,「第10集」排在「第2集」前面。现在是:
标点 < 数字(按数值)< 字母(拼音和拉丁字母混排,不分大小写、不分重音)< 其余文字。
"""

from __future__ import annotations

import random

from sqlalchemy import inspect, text

from app.core.collation import name_sort_key
from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_assets_get_a_name_sort_key
from app.db.models import Asset
from tests.util import fresh_client, insert_asset

#: 素材库按名称排出来该是这个顺序。
ORDER = [
    "_x", "1号", "2号", "10号", "a", "阿", "a1", "a2", "a10", "apple", "B站", "Banana", "草莓", "重庆",
    "第2集", "第10集", "éclair", "Ölfass", "行走", "银行", "Zebra", "zhang", "张三", "赵", "中文",
]


def test_排序键排出来是这个顺序() -> None:
    shuffled = ORDER[:]
    random.Random(7).shuffle(shuffled)
    assert sorted(shuffled, key=name_sort_key) == ORDER


def test_中文按拼音和英文混排() -> None:
    assert name_sort_key("阿") < name_sort_key("Apple") < name_sort_key("Banana") < name_sort_key("草莓")
    assert name_sort_key("阿姨") < name_sort_key("爱"), "一个音节一段:a·yi 排在 ai 前面"


def test_数字按大小() -> None:
    assert name_sort_key("第2集") < name_sort_key("第10集") < name_sort_key("第100集")
    assert name_sort_key("v9") < name_sort_key("v010") < name_sort_key("v11")


def test_大小写_全角_重音只在别的都一样时才分先后() -> None:
    names = ["éclair", "ＢＡＮＡＮＡ", "eclair", "banana", "Banana", "fig", "apple"]
    ordered = sorted(names, key=name_sort_key)
    assert ordered[0] == "apple" and ordered[-1] == "fig"
    assert set(ordered[1:4]) == {"Banana", "banana", "ＢＡＮＡＮＡ"}
    assert set(ordered[4:6]) == {"eclair", "éclair"}
    assert sorted(reversed(names), key=name_sort_key) == ordered, "同样的名单不管怎么给,排出来是同一个顺序"


def test_多音字按词组读() -> None:
    assert name_sort_key("重庆") < name_sort_key("第一"), "重庆读 chong"
    assert name_sort_key("银行") > name_sort_key("行走"), "银行 yin·hang,行走 xing·zou"


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _walk(client, ws: str, limit: int) -> list[str]:
    names: list[str] = []
    cursor = None
    for _ in range(100):
        params = {"workspace_id": ws, "sort": "name", "limit": limit, **({"cursor": cursor} if cursor else {})}
        page = client.get("/api/assets", params=params).json()
        names += [item["name"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return names
    raise AssertionError("游标翻不到头")


def test_素材库按名称排序是这个顺序_一页页翻过去也是() -> None:
    client = fresh_client()
    ws = _workspace(client)
    shuffled = ORDER[:]
    random.Random(11).shuffle(shuffled)
    for name in shuffled:
        insert_asset(ws, kind="image", name=name)
    #: 同名的两份:排序键一样,按 id 定先后,翻页时不重复、不漏掉。
    twins = [insert_asset(ws, kind="image", name="草莓") for _ in range(2)]

    expected = ORDER[:]
    expected[expected.index("草莓"):expected.index("草莓") + 1] = ["草莓"] * 3
    assert _walk(client, ws, limit=100) == expected
    assert _walk(client, ws, limit=2) == expected
    ids = [item["id"] for item in client.get("/api/assets", params={"workspace_id": ws, "sort": "name", "limit": 100}).json()["items"]]
    assert set(twins) <= set(ids)


def test_改名之后排序跟着变() -> None:
    client = fresh_client()
    ws = _workspace(client)
    banana = insert_asset(ws, kind="image", name="Banana")
    insert_asset(ws, kind="image", name="草莓")
    insert_asset(ws, kind="image", name="apple")
    assert _walk(client, ws, limit=10) == ["apple", "Banana", "草莓"]

    renamed = client.patch(f"/api/assets/{banana}", json={"name": "阿姨的香蕉"})
    assert renamed.status_code == 200, renamed.text
    assert _walk(client, ws, limit=10) == ["阿姨的香蕉", "apple", "草莓"]


def test_排序键只在名字写进去的那一处算_新建改名都经过它() -> None:
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind="audio", name="第2集 旁白")
        db.add(asset)
        db.flush()
        assert asset.name_sort_key == name_sort_key("第2集 旁白")
        asset.name = "Banana"
        assert asset.name_sort_key == name_sort_key("Banana")
        db.rollback()


def test_迁移给老表补上排序键_老素材都算好_再跑一次什么都不做() -> None:
    ws = _workspace(fresh_client())
    for name in ("阿", "Banana", "第10集"):
        insert_asset(ws, kind="image", name=name)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_assets_workspace_intermediate_name"))
        conn.execute(text("ALTER TABLE assets DROP COLUMN name_sort_key"))
    engine.dispose()
    assert "name_sort_key" not in {column["name"] for column in inspect(engine).get_columns("assets")}

    _migrate_assets_get_a_name_sort_key()
    _migrate_assets_get_a_name_sort_key()
    engine.dispose()

    assert "idx_assets_workspace_intermediate_name" in {index["name"] for index in inspect(engine).get_indexes("assets")}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name, name_sort_key FROM assets")).all()
    assert {name: key for name, key in rows} == {name: name_sort_key(name) for name in ("阿", "Banana", "第10集")}
