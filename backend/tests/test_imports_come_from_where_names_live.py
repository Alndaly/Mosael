"""**一个名字只有一个来源:从定义它的那个模块导入。**

此前到处是「转出」:模块拆成几个之后,原来那个模块把新位置的名字再导出一遍(「调用方照旧从这里取」);包的
`__init__` 把子模块的名字收上来;适配层把共享格式包里的名字接过来。一个名字于是有两三个来源 —— 读的人分不清
哪里是本体,打补丁的测试补在转出的那一份上,调用方读的是本体,补丁静默失效。

两条规则,都按语法树查:

1. `from app.x import name`(以及 `mosael_formats.x`):`name` 必须是 `app.x` **自己定义**的(函数、类、赋值),
   或者是它的子模块 —— 不能是 `app.x` 自己也是 import 进来的。
2. `app/` 下模块的 `__all__` 只列本模块定义的名字:列了别处的,就是在宣称「可以从这里取」。

例外只有三个**装配入口**:`app.db.models`、`app.api.schemas`(切片是实现细节,见 test_domain_assembly_entries)
和 `app.ai.providers`(领域使用供应商的稳定公共 Interface,ADR 0010;见 test_provider_architecture)。它们本来就是
给外面取的入口,这是定下来的设计,不是兼容。

红了怎么办:把 import 改成从定义处取(`from app.domain.workflows.errors import WorkflowDomainError`,
不是 `from app.domain.workflows import …`)。**不要**为了少改几处在原模块里转出 —— 那正是这条要拦的。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import functools
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FORMATS = BACKEND.parent / "packages" / "mosael-formats" / "src"
ASSEMBLY = {"app.db.models", "app.api.schemas", "app.ai.providers"}
ROOTS = ("app", "mosael_formats")


def _exists_exactly(path: pathlib.Path) -> bool:
    """按大小写精确判断:macOS 的文件系统不分大小写,`NODE_TYPES` 会被当成 `node_types.py`。"""
    return path.exists() and path.name in {entry.name for entry in path.parent.iterdir()}


def _module_file(module: str) -> pathlib.Path | None:
    base_dir = FORMATS if module.split(".")[0] == "mosael_formats" else BACKEND
    base = base_dir / module.replace(".", "/")
    if _exists_exactly(base) and (base / "__init__.py").is_file():
        return base / "__init__.py"
    if _exists_exactly(base.with_suffix(".py")):
        return base.with_suffix(".py")
    return None


def _is_submodule(module: str, name: str) -> bool:
    return _module_file(f"{module}.{name}") is not None


@functools.cache
def _tree(module: str) -> ast.Module | None:
    path = _module_file(module)
    return ast.parse(path.read_text(encoding="utf-8")) if path is not None else None


def _top_level(nodes: list[ast.stmt]):
    """模块顶层的语句,连同 if / try 分支里的(条件定义、可选依赖也算定义在这里)。"""
    for node in nodes:
        yield node
        if isinstance(node, ast.If):
            yield from _top_level(node.body)
            yield from _top_level(node.orelse)
        elif isinstance(node, ast.Try):
            for block in (node.body, node.orelse, node.finalbody, *(h.body for h in node.handlers)):
                yield from _top_level(block)


def _bound_by(target: ast.expr) -> set[str]:
    """赋值左边真正绑定了哪些名字:`a = …`、`a, b = …` 算;`a[k] = …`、`a.x = …` 不算 —— 那是在改一个已有的对象。"""
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return {name for elt in target.elts for name in _bound_by(elt)}
    if isinstance(target, ast.Starred):
        return _bound_by(target.value)
    return set()


@functools.cache
def _defined(module: str) -> frozenset[str]:
    """这个模块自己定义的名字(函数、类、赋值的目标)。"""
    tree = _tree(module)
    if tree is None:
        return frozenset()
    names: set[str] = set()
    for node in _top_level(tree.body):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                names |= _bound_by(target)
        elif isinstance(node, ast.TypeAlias):
            names.add(node.name.id)
    return frozenset(names)


def _module_name(path: pathlib.Path) -> str:
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _absolute(path: pathlib.Path, node: ast.ImportFrom) -> str:
    """`from .x import y` 换成绝对模块名(相对导入也算:worker 那几个文件在包里时就这么写)。"""
    if node.level == 0:
        return node.module or ""
    package = _module_name(path).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, node.module] if node.module else base)


def _sources() -> list[pathlib.Path]:
    files = [*(BACKEND / "app").rglob("*.py"), *(BACKEND / "tests").rglob("*.py"), *(BACKEND / "scripts").rglob("*.py")]
    return sorted([*files, BACKEND / "mcp_server.py"])


def test_名字从定义它的模块导入() -> None:
    borrowed: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = _absolute(path, node)
            if not module or module.split(".")[0] not in ROOTS or module in ASSEMBLY or _tree(module) is None:
                continue
            for alias in node.names:
                if alias.name == "*" or _is_submodule(module, alias.name) or alias.name in _defined(module):
                    continue
                borrowed.append(f"{path.relative_to(BACKEND)}:{node.lineno}  from {module} import {alias.name}")
    assert not borrowed, (
        "这些 import 借道了别的模块 —— 名字不是在那里定义的,改成从定义处取:\n  " + "\n  ".join(borrowed)
    )


def test_all_只列本模块定义的名字() -> None:
    foreign: list[str] = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        module = _module_name(path)
        if module in ASSEMBLY:
            continue
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)):
                continue
            for elt in getattr(node.value, "elts", []):
                name = elt.value if isinstance(elt, ast.Constant) else None
                if isinstance(name, str) and name not in _defined(module) and not _is_submodule(module, name):
                    foreign.append(f"{path.relative_to(BACKEND)}  __all__ 里的 {name}")
    assert not foreign, "这些 __all__ 列了别处定义的名字(等于宣称可以从这里取):\n  " + "\n  ".join(foreign)


def test_口径自己有人看着() -> None:
    """扫描面空了、或者「定义」认不出来的话,上面两条天然为真。"""
    assert "WorkflowDomainError" in _defined("app.domain.workflows.errors")
    assert "WorkflowDomainError" not in _defined("app.domain.workflows")
    assert "parse" in _defined("mosael_formats.plugin_manifest")
    assert not _is_submodule("app.domain.workflows", "NODE_TYPES"), "大小写不分的文件系统上也不能把常量认成子模块"
    assert len(_sources()) > 500
