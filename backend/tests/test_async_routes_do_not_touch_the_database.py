"""棘轮:**`async def` 的路由不拿数据库会话。**

`async def` 端点的函数体跑在事件循环上。数据库是同步的(SQLAlchemy + sqlite3),在那里查一次库、写一次库,整个后端的
所有请求 —— 播放中的视频、智能体的 SSE、别的页面 —— 都排在它后面等。实测导入两千条字幕的端点是 `async def`
(为了 `await file.read()`),那十八秒里 `/api/health` 一个都答不出来;busy_timeout 碰上写锁时一等就是五秒。

所以要碰库的端点写成普通的 `def`(FastAPI 把它放进线程池;上传用 `upload.file.read()` 同步读);非得是 async 的
(要 `await request.form()`)把库的那一段交给线程池、会话在那边开。判据:async 端点的参数里不许出现 `Tx` / `DbSession`。
"""

from __future__ import annotations

import ast
import pathlib

# 进 docs/CONVENTIONS.md 的棘轮清单(scripts/sync-ratchet-docs.py 生成)。
RATCHET = True

ROUTES = pathlib.Path(__file__).resolve().parents[1] / "app" / "api" / "routes"
SESSION_DEPENDENCIES = {"Tx", "DbSession", "Session"}


def _is_route(function: ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in {"get", "post", "put", "patch", "delete", "api_route"}:
            return True
    return False


def _offenders() -> list[str]:
    found = []
    for path in sorted(ROUTES.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.AsyncFunctionDef) or not _is_route(node):
                continue
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            for argument in arguments:
                annotation = argument.annotation
                name = annotation.id if isinstance(annotation, ast.Name) else getattr(annotation, "attr", None)
                if name in SESSION_DEPENDENCIES:
                    found.append(f"{path.relative_to(ROUTES).as_posix()}:{node.lineno} {node.name}({argument.arg}: {name})")
    return found


def test_async_routes_take_no_database_session() -> None:
    offenders = _offenders()
    assert not offenders, (
        "这些 async 端点拿了数据库会话 —— 它们的库操作跑在事件循环上,期间所有请求都停着。改成 `def`"
        "(上传用 upload.file.read() 同步读),或者把库的那一段交给线程池、会话在那边开:\n  " + "\n  ".join(offenders)
    )


def test_the_scan_sees_async_routes() -> None:
    """扫描面自己也要有人看着:一个 async 端点都认不出来时,上面那条天然成立。"""
    routes = [
        node.name
        for path in ROUTES.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.AsyncFunctionDef) and _is_route(node)
    ]
    assert "dictate" in routes, f"认不出 async 端点了(找到的:{routes})—— 路由的写法变了,先修这条测试"
