"""**路由里一处都不直接读写数据库。**

路由只做 HTTP 转译与鉴权(docs/ARCHITECTURE「后端:领域内核 + 薄路由」),查哪几行、改哪一列、删之前要先停掉什么,
都是领域的事。写在路由里的话,智能体工具、工作流节点、飞书回调这几个入口要么各补一份、要么漏掉:删工作流时停用
绑着它的定时任务和触发器就曾经只写在删除的路由里。

这里扫 `app/api/routes` 下对会话的直接调用(`db.get / scalars / scalar / execute / add / delete …`)和
SQLAlchemy 的 `select / update / delete / insert` 构造。曾经冻结过 21 个文件、47 处,全部下沉之后收紧成零:
新加一处就红 —— 把它写成领域函数(多半是 `domain/<领域>/use_cases.py` 里的一个用例),路由调它。

`db.commit()` / `db.refresh()` 不算:提交是入口层的事(见 core/unit_of_work),刷新是序列化前取最新值。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "routes"

#: 会话上的这些方法算「直接读写数据库」。
SESSION_CALLS = {"get", "scalars", "scalar", "execute", "add", "add_all", "delete", "query", "merge"}
#: 构造 SQL 的这些函数也算。
SQL_BUILDERS = {"select", "update", "delete", "insert"}

def database_calls(source: str) -> int:
    """这段源码里直接读写数据库的调用有几处(见文件开头的口径)。"""
    count = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr in SESSION_CALLS
                and isinstance(func.value, ast.Name) and func.value.id in {"db", "session"}):
            count += 1
        elif isinstance(func, ast.Name) and func.id in SQL_BUILDERS:
            count += 1
    return count


def test_路由里不直接读写数据库() -> None:
    found = {
        path.relative_to(ROUTES).as_posix(): count
        for path in sorted(ROUTES.rglob("*.py"))
        if (count := database_calls(path.read_text(encoding="utf-8")))
    }
    assert not found, (
        "这些路由直接读写了数据库(文件:处数)。写成领域函数,路由调它:\n  "
        + "\n  ".join(f"{name}: {count}" for name, count in sorted(found.items()))
    )


def test_口径自己有人看着() -> None:
    """扫描面空了的话上面那条天然为真。"""
    assert database_calls("db.get(User, 1)\nselect(User)\ndb.commit()\n") == 2
    assert len(list(ROUTES.rglob("*.py"))) > 20
