"""路由用到 `user`,就必须把它**声明成参数**。

真机上前端每进一次 AI Studio,浏览器控制台就多一条:

    Access to fetch at 'http://127.0.0.1:8800/api/agent/manifest' … blocked by CORS policy:
    No 'Access-Control-Allow-Origin' header is present on the requested resource.

看起来像跨域配置的事,其实不是 —— 带上 token 直接打是 **500**。这两个路由

    def get_agent_skills(db: DbSession) -> …:      return list_agent_skills(db, user.id)
    def get_agent_manifest(db: DbSession) -> …:    … list_agent_skills(db, user.id) …

都在用一个**没有声明的 `user`**,NameError 一路抛到 Starlette 的 ServerErrorMiddleware ——
它在 CORSMiddleware **外面**生成响应,所以那条 500 不带跨域头,浏览器只好报成 CORS。
真正的错误被换了一张脸,于是它在控制台里躺了很久没人认出来。

同文件其它十几个路由都写着 `user: CurrentUser`,这两个是加进来时漏的(077fe42)。
**一个只在被请求时才炸的名字,谁都不会替你发现** —— 所以除了把它修好,再钉一条:
routes 里任何函数体用到 `user`,签名里就得有 `user`。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.util import fresh_client

ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"


def _functions_using_an_undeclared_user() -> list[str]:
    offenders: list[str] = []
    for path in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            declared = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            if "user" in declared:
                continue
            # 函数体里出现 `user.…` / `user` 这个自由名
            uses = any(
                isinstance(child, ast.Name) and child.id == "user" and isinstance(child.ctx, ast.Load)
                for child in ast.walk(node)
            )
            # 自己在体内绑定的 user(赋值、for、with as)不算
            bound = any(
                isinstance(child, ast.Name) and child.id == "user" and isinstance(child.ctx, ast.Store)
                for child in ast.walk(node)
            )
            if uses and not bound:
                offenders.append(f"{path.name}:{node.lineno} {node.name}")
    return offenders


def test_no_route_uses_a_user_it_never_declared() -> None:
    """签名里没有 user,函数体里却用 user —— 这条路由一被请求就 500。"""
    offenders = _functions_using_an_undeclared_user()

    assert offenders == [], (
        "这些路由用了没声明的 `user`,一请求就 NameError → 500(浏览器里还会显示成 CORS):\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("path", ["/api/agent/manifest", "/api/agent/skills"])
def test_the_two_that_were_broken_answer(path: str) -> None:
    """按用户实际走的路验一遍:登录后请求,拿到的是内容,不是 500。"""
    client = fresh_client()

    resp = client.get(path)

    assert resp.status_code == 200, resp.text
