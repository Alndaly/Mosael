"""`sqlite3.connect()` 不许直接当 `with` 用 —— 那个 with 管事务,不关连接。

Python 的 `sqlite3.Connection` 是个**假的**上下文管理器:`__exit__` 只 commit 或 rollback,
连接和它持有的文件句柄照旧活着。写法看上去和 `open()` 一模一样,行为却不是。

POSIX 上这个错误不产生任何症状 —— 改名、删除一个还开着的文件都是合法的。Windows 上
`os.replace()` 会抛 `WinError 32: 该文件正由另一进程使用`。于是它成了一类**只在 Windows 上、
且只在特定路径上**才现形的缺陷,mac 开发机和 Linux CI 一起给它放行。

代价已经付过一次:v1.0.0-beta2 的 Windows 包在任何有老库要升级的机器上都起不来。
`create_upgrade_snapshot` 把快照写进 `.partial`,校验完整性时用了这个写法,改名成 `.sqlite`
时撞上自己没关的连接 → lifespan 抛异常 → uvicorn 退出 3 → 用户看到应用一直转圈。
同一处写法还泄漏着待还原备份库的句柄,而还原正指望「Windows 看不到开着的 SQLite」。

所以这条棘轮是**结构检查而不是运行时用例** —— 运行时用例在 mac 和 Linux 上永远是绿的,
守不住任何东西。正确写法:

    with closing(sqlite3.connect(path)) as db:   # contextlib.closing
        ...

需要事务语义就两层套:`with closing(conn) as db, db:`。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# 存量越界。**只减不增** —— 修好一处就从这里删掉。
ALLOWLIST: frozenset[tuple[str, int]] = frozenset()


def _is_sqlite_connect(node: ast.expr) -> bool:
    """认 `sqlite3.connect(...)`,不认变量名恰好叫 connect 的东西。"""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sqlite3"
    )


def _scan() -> set[tuple[str, int]]:
    found: set[tuple[str, int]] = set()
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        rel = str(path.relative_to(BACKEND_ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.With, ast.AsyncWith)):
                continue
            for item in node.items:
                # 裹了 closing() 就不是这里要拦的形状 —— 那时 context_expr 是 closing(...)。
                if _is_sqlite_connect(item.context_expr):
                    found.add((rel, node.lineno))
    return found


def test_sqlite_connections_are_closed_not_just_committed() -> None:
    offenders = sorted(_scan() - ALLOWLIST)
    assert not offenders, (
        "sqlite3.connect() 的 with 只结束事务、不关连接;Windows 上随后的 os.replace/删除会抛 "
        "WinError 32。改成 `with closing(sqlite3.connect(...)) as db:`。越界处:"
        f"{offenders}"
    )


def test_allowlist_only_shrinks() -> None:
    stale = sorted(ALLOWLIST - _scan())
    assert not stale, f"已经修好了,从 ALLOWLIST 删掉:{stale}"
