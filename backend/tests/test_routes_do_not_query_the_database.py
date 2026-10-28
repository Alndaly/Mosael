"""棘轮:**路由里直接读写数据库的地方只减不增。**

路由只做 HTTP 转译与鉴权(docs/ARCHITECTURE「后端:领域内核 + 薄路由」),查哪几行、改哪一列、删之前要先停掉什么,
都是领域的事。写在路由里的话,智能体工具、工作流节点、飞书回调这几个入口要么各补一份、要么漏掉:删工作流时停用
绑着它的定时任务和触发器就曾经只写在删除的路由里。

这里按文件数 `app/api/routes` 下对会话的直接调用(`db.get / scalars / scalar / execute / add / delete …`)和
SQLAlchemy 的 `select / update / delete / insert` 构造,和下面的表对不上就红:

- 新加一处 → 红。把它写成领域函数(多半是 `domain/<领域>/use_cases.py` 里的一个用例),路由调它。
- 挪走一处 → 也红,把表里的数改小;清零了就删掉那一行 —— 表只能往下走,不然它会变成谁都能往里加的白名单。

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

#: 文件(相对 app/api/routes)→ 还剩几处。只减不增。
FROZEN = {
    "agent.py": 5,
    "agent_credentials.py": 1,
    "agent_tools.py": 2,
    "auth.py": 1,
    "blender.py": 2,
    "browser_profiles.py": 3,
    "confirmations.py": 1,
    "entities.py": 3,
    "hooks.py": 4,
    "job_worker.py": 1,
    "jobs.py": 2,
    "oauth.py": 4,
    "plugins.py": 2,
    "publish.py": 3,
    "publish_worker.py": 2,
    "settings/provider_defaults.py": 1,
    "settings/provider_models.py": 1,
    "settings/provider_pricing.py": 2,
    "settings/provider_profiles.py": 2,
    "voices.py": 1,
    "workspaces.py": 4,
}


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


def test_路由里直接读写数据库的地方只减不增() -> None:
    now = {
        path.relative_to(ROUTES).as_posix(): found
        for path in sorted(ROUTES.rglob("*.py"))
        if (found := database_calls(path.read_text(encoding="utf-8")))
    }
    grown = {name: (FROZEN.get(name, 0), found) for name, found in now.items() if found > FROZEN.get(name, 0)}
    assert not grown, (
        "这些路由里多出了直接读写数据库的调用(存量 → 现在)。写成领域函数,路由调它:\n  "
        + "\n  ".join(f"{name}: {was} → {found}" for name, (was, found) in sorted(grown.items()))
    )
    shrunk = {name: (was, now.get(name, 0)) for name, was in FROZEN.items() if now.get(name, 0) < was}
    assert not shrunk, (
        "这些路由里直接读写数据库的地方变少了,把表里的数改小(清零就删掉那一行):\n  "
        + "\n  ".join(f"{name}: {was} → {found}" for name, (was, found) in sorted(shrunk.items()))
    )


def test_口径自己有人看着() -> None:
    """扫描面空了的话上面那条天然为真。"""
    assert database_calls("db.get(User, 1)\nselect(User)\ndb.commit()\n") == 2
    assert len(list(ROUTES.rglob("*.py"))) > 20
