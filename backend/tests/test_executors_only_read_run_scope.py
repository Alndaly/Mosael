"""节点执行器只从运行作用域里读 workspace_id / id / name 三样。

执行器的签名是 `(db, scope: RunScope, config)`(见 workflows/executors)。此前第二个参数是
Workflow 这个 ORM 对象,而执行器实际只读了它三个属性 —— 签名比用法宽,节点就只能在工作流里
跑。收窄之后创意画板可以用自己的作用域跑同一批节点;这条棘轮防止它悄悄变回去:谁在执行器里
读了 `scope.graph`、`scope.revision`,或者把 scope 交给一个不认 RunScope 的函数,画板那条路
就会在运行时才炸。

放行的用法只有三种:读允许的属性、`getattr(scope, "<允许的属性>", …)`、原样交给本包里
同样把那个参数声明成 RunScope 的函数(那个函数随后同样受这条检查)。
"""

from __future__ import annotations

import ast
from pathlib import Path

RATCHET = True

EXECUTORS_DIR = Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows" / "executors"
ALLOWED = frozenset({"workspace_id", "id", "name"})


def _modules() -> dict[str, ast.Module]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(EXECUTORS_DIR.glob("*.py"))
        if path.name != "__init__.py"
    }


def _params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    return [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]


def _annotation(arg: ast.arg) -> str:
    return ast.unparse(arg.annotation) if arg.annotation is not None else ""


def _functions(modules: dict[str, ast.Module]) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for tree in modules.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(node.name, node)
    return out


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _accepts_scope(callee: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call, use: ast.Name) -> bool:
    """这次调用把 scope 交到了 callee 的哪个参数上,那个参数是不是 RunScope。"""
    params = _params(callee)
    for index, value in enumerate(call.args):
        if value is use:
            return index < len(params) and _annotation(params[index]) == "RunScope"
    for keyword in call.keywords:
        if keyword.value is use:
            return any(p.arg == keyword.arg and _annotation(p) == "RunScope" for p in params)
    return False


def _violations(modules: dict[str, ast.Module]) -> list[str]:
    functions = _functions(modules)
    problems: list[str] = []
    for filename, tree in modules.items():
        parents = _parents(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = {arg.arg for arg in _params(fn) if _annotation(arg) == "RunScope"}
            for arg in _params(fn):
                if _annotation(arg) == "Workflow":
                    problems.append(f"{filename}:{fn.lineno} {fn.name} 的 {arg.arg} 还声明成 Workflow")
            if not names:
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Name) and node.id in names and isinstance(node.ctx, ast.Load)):
                    continue
                parent = parents.get(node)
                where = f"{filename}:{node.lineno} {fn.name}"
                if isinstance(parent, ast.Attribute) and parent.value is node:
                    if parent.attr not in ALLOWED:
                        problems.append(f"{where} 读了 {node.id}.{parent.attr}")
                    continue
                if isinstance(parent, ast.Call) and node in parent.args[:1] and ast.unparse(parent.func) == "getattr":
                    attr = parent.args[1] if len(parent.args) > 1 else None
                    if not (isinstance(attr, ast.Constant) and attr.value in ALLOWED):
                        problems.append(f"{where} 用 getattr 读了 {ast.unparse(attr) if attr else '?'}")
                    continue
                if isinstance(parent, ast.keyword):
                    parent = parents.get(parent)
                if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name):
                    callee = functions.get(parent.func.id)
                    if callee is not None and _accepts_scope(callee, parent, node):
                        continue
                problems.append(f"{where} 把 {node.id} 用在了 `{ast.unparse(parent) if parent else node.id}`")
    return problems


def test_执行器只读运行作用域的三个属性() -> None:
    problems = _violations(_modules())
    assert not problems, "执行器越过了 RunScope(workspace_id / id / name):\n" + "\n".join(problems)


def test_每个注册的执行器第二个参数都是_RunScope() -> None:
    """登记进注册表的执行器,签名就是 Handler 的样子 —— 第二个参数漏标,上面那条就查不到它。"""
    unscoped: list[str] = []
    for filename, tree in _modules().items():
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            registered = any(
                isinstance(dec, ast.Call) and ast.unparse(dec.func) == "register" for dec in fn.decorator_list
            )
            if registered and (len(fn.args.args) < 2 or _annotation(fn.args.args[1]) != "RunScope"):
                unscoped.append(f"{filename}:{fn.lineno} {fn.name}")
    assert not unscoped, "这些执行器的第二个参数没声明成 RunScope:\n" + "\n".join(unscoped)


def test_棘轮认得出越界() -> None:
    """检查本身要能抓到人:读别的属性、getattr 绕一下、把 scope 交给不认它的函数,都算越界;
    交给同样声明 RunScope 的函数不算。"""
    source = """
def helper(db, thing, config): ...
def ok(db, scope: RunScope, config): ...
def bad(db, scope: RunScope, config):
    scope.graph
    getattr(scope, "revision", None)
    helper(db, scope, config)
    ok(db, scope, config)
    ok(db, config=config, scope=scope)
    return scope.workspace_id, getattr(scope, "name", "")
"""
    problems = _violations({"fake.py": ast.parse(source)})
    assert [line.split(" ")[0] for line in problems] == ["fake.py:5", "fake.py:6", "fake.py:7"], problems
