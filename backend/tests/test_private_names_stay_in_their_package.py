"""棘轮:下划线开头的名字不跨包引用。

私有函数被别处借用时,它就是一个没人承认的接口:改它的人不知道外面有人在用,借它的人也不知道
自己绕过了什么。审查时找到过四处 —— 路由从 worker 模块借「有没有在跑」、从另一个路由借
「这条连接是不是我的」、从领域借 cookie 文件、从别的领域借转写文本 —— 每一处背后都是一条
本该公开、并且放在对的地方的规则。

同一个包里互相用是允许的(那是包的内部实现)。判据走 AST。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _module(path: pathlib.Path) -> str:
    parts = list(path.relative_to(APP.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package(module: str, *, is_package: bool) -> str:
    return module if is_package else module.rpartition(".")[0]


def test_私有名字不跨包引用() -> None:
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        importer = _module(path)
        importer_package = _package(importer, is_package=path.name == "__init__.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.")):
                continue
            private = [alias.name for alias in node.names if alias.name.startswith("_")]
            if not private:
                continue
            source_package = node.module.rpartition(".")[0]
            if importer_package == source_package or importer_package.startswith(source_package + "."):
                continue
            offenders.append(f"{path.relative_to(APP.parent)}:{node.lineno} 从 {node.module} 借 {', '.join(private)}")
    assert not offenders, "这些私有名字被跨包引用 —— 把规则公开并放到对的地方:\n" + "\n".join(offenders)
