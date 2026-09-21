"""执行器**真正返回**的键,必须在节点注册表里声明过。

## 为什么这条看不出来

一个节点的 `outputs` 是给三样东西用的:画布上那几个可连的接点、`{{节点.键}}` 的合法性校验、
以及属性面板里"这一步会产出什么"。而执行器返回的字典是**运行时**才存在的。两边对不上时:

- 返回了但没声明 → 那个值**接不出去、引用不到、界面上不存在**。数据一直在,只是没有任何
  地方能看见它。本仓库真实发生过:`scene_render` 加了 `model_warnings`(哪几件模型没渲进去、
  为什么),领域层返回了、接口 schema 也有,唯独节点没声明 —— 于是工作流里那条信息等于不存在,
  而没有任何测试会红。
- 声明了但从不返回 → 连出去的线永远取到空值,而"空"和"还没跑"在界面上长得一样。

两种都不报错。所以拿 AST 静态对一遍。

## 透传的那几个

有些执行器直接 `return 别处的函数(...)`,键不在自己这儿。那就顺着名字把那个函数找出来接着看 ——
**不能因为"静态看不到"就放过**:`scene_render` 正是这一种,而它就是出问题的那一个。找不到
定义的(第三方、动态构造)才登记豁免,并写清楚理由。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from collections.abc import Callable
from pathlib import Path

from app.domain.workflows import NODE_TYPES

BACKEND = Path(__file__).resolve().parent.parent
EXECUTORS = BACKEND / "app" / "domain" / "workflows" / "executors"

#: 解 `{**ref}` 里那个 `ref`:给一个表达式,答出它有哪些键(答不出就是 None)。
Spread = Callable[[ast.expr], "set[str] | None"]

#: 键在运行时才知道,静态对不了。每一条都要写清楚为什么。
DYNAMIC: dict[str, str] = {
    # start 的产出就是用户自己定义的那些参数名(声明里写成 `*params`)。
    "start": "产出是用户定义的启动参数,名字运行时才有",
    # 子工作流的产出是被调用那张图的产出,同样运行时才知道。
    "call_workflow": "产出是被调用工作流的产出",
    "subgraph": "同上",
}


def _module_index() -> dict[str, ast.FunctionDef]:
    """`app/domain` 下所有顶层函数,按名字索引 —— 用来顺着透传找过去。"""
    index: dict[str, ast.FunctionDef] = {}
    for path in (BACKEND / "app" / "domain").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 语法错误由别的测试管
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                index.setdefault(node.name, node)  # type: ignore[arg-type]
    return index


def _dict_keys(node: ast.Dict, spread: Spread) -> set[str] | None:
    """字面量字典的键。`{**ref, "text": ...}` 里的 `**ref` 交给 `spread` 去解。"""
    keys: set[str] = set()
    for key, value in zip(node.keys, node.values):
        if key is None:  # `**something`
            merged = spread(value)
            if merged is None:
                return None
            keys |= merged
        elif isinstance(key, ast.Constant) and isinstance(key.value, str):
            keys.add(key.value)
        else:
            return None  # 算出来的键:看不透
    return keys


def _literal_keys(fn: ast.AST, spread: Spread) -> set[str] | None:
    """这个函数 `return` 出去的字典有哪些键;**一处读不透就整个返回 None**。

    三种写法都要认:直接 `return {...}`;**先攒进一个变量再 return** —— 后者是本仓库最常见的
    形状(`out = {...}` … `out["k"] = v` … `return out`),而 `scene_render` 那次漏掉的
    `model_warnings` 正是这么加进去的;以及带类型标注的 `out: dict[str, Any] = {...}`。

    **"没有键"和"读不出来"是两件事。** 早先这里两种都返回空集合,于是 `browser_close` 的
    `return {}` 被当成读不出来而点名报错 —— 一条棘轮误报,和它漏报一样会让人学会忽略它。
    """
    assigned: dict[str, set[str]] = {}
    for node in ast.walk(fn):
        # out = {...} / out: dict[str, Any] = {...}
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
            keys = _dict_keys(node.value, spread)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and keys is not None:
                    assigned[target.id] = set(keys)
        # out["k"] = v
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                        and target.value.id in assigned):
                    assigned[target.value.id].add(target.slice.value)

    found: set[str] = set()
    readable = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        if isinstance(node.value, ast.Constant) and node.value.value is None:
            continue  # `return None`:这条路不产出键
        if isinstance(node.value, ast.Dict):
            keys = _dict_keys(node.value, spread)
            if keys is None:
                return None
            found |= keys
            readable = True
        elif isinstance(node.value, ast.Name) and node.value.id in assigned:
            found |= assigned[node.value.id]
            readable = True
    return found if readable else None


def _call_name(call: ast.Call) -> str:
    return getattr(call.func, "id", None) or getattr(call.func, "attr", None) or ""


def _returned_keys(fn: ast.AST, index: dict[str, ast.FunctionDef], depth: int = 0) -> set[str] | None:
    """这个函数会返回哪些键。透传和 `**展开` 都顺着名字找下去;实在看不透返回 None。"""

    def spread(value: ast.expr) -> set[str] | None:
        """`{**ref, ...}` 里的 `ref` 从哪儿来 —— 顺着赋值找到那次调用,再看它返回什么。

        `note_read` 就是这一种(`ref = read_reference(...)` 然后 `return {**ref, "text": ...}`)。
        把它登记成豁免也能让测试变绿,但那是**把读不动的地方记下来**,不是读懂它 —— 而这些键
        静态就在 `read_reference` 的 return 里写着。
        """
        if depth > 2 or not isinstance(value, ast.Name):
            return None
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            if not any(isinstance(t, ast.Name) and t.id == value.id for t in node.targets):
                continue
            target = index.get(_call_name(node.value))
            if target is not None:
                return _returned_keys(target, index, depth + 1)
        return None

    keys = _literal_keys(fn, spread)

    passthrough: set[str] | None = None
    if depth <= 2:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
                continue
            target = index.get(_call_name(node.value))
            if target is None:
                continue
            nested = _returned_keys(target, index, depth + 1)
            if nested is not None:
                passthrough = (passthrough or set()) | nested

    if keys is None and passthrough is None:
        return None
    return (keys or set()) | (passthrough or set())


def _executors() -> list[tuple[str, ast.FunctionDef, str]]:
    found: list[tuple[str, ast.FunctionDef, str]] = []
    for path in EXECUTORS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call)
                        and getattr(decorator.func, "id", "") == "register"
                        and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)):
                    found.append((decorator.args[0].value, node, path.name))  # type: ignore[arg-type]
    return found


def test_执行器返回的键都声明过() -> None:
    index = _module_index()
    undeclared: list[str] = []
    unreadable: list[str] = []
    for name, fn, filename in _executors():
        if name in DYNAMIC:
            continue
        spec = NODE_TYPES.get(name)
        assert spec is not None, f"{filename} 注册了 {name},但 NODE_TYPES 里没有它"
        keys = _returned_keys(fn, index)
        if keys is None:
            # **看不懂要说出来,不能静默跳过。** 第一版在这里 `continue`,于是三个节点悄悄
            # 没被检查过,而测试是绿的 —— 一条在该响时沉默的棘轮比没有更坏,因为它还让人放心。
            unreadable.append(f"{name}({filename})")
            continue
        extra = keys - set(spec.get("outputs") or [])
        if extra:
            undeclared.append(f"{name}({filename}): {', '.join(sorted(extra))}")
    assert not undeclared, (
        "这些键执行器返回了,但节点没声明 —— 它们接不出去、引用不到、界面上等于不存在:\n  "
        + "\n  ".join(undeclared)
    )
    assert not unreadable, (
        "这些执行器的返回形状静态读不出来,于是它们**根本没被检查**。要么把返回改成看得懂的"
        "形状(直接 return 字面量,或先攒进一个变量再 return),要么登记进 DYNAMIC 并写明理由:\n  "
        + "\n  ".join(unreadable)
    )


def test_豁免清单只减不增() -> None:
    """看不透的那几个要一直说得出理由。清单变长时,先问问是不是又多了一处静态对不了的返回。"""
    assert len(DYNAMIC) <= 3
    for reason in DYNAMIC.values():
        assert reason.strip()


def test_每个声明的输出都有标签和类型说得通() -> None:
    """声明了却没人返回同样是坏的:连出去的线永远取到空,而"空"和"还没跑"在界面上一个样。

    这一半没法静态证伪(执行器可能条件性地不返回某个键),所以只钉住能钉的:声明的每个键
    都要有中文标签,否则界面上露出的是英文键名。
    """
    from app.domain.workflows import output_label

    missing: list[str] = []
    for name, spec in NODE_TYPES.items():
        for key in spec.get("outputs") or []:
            if key.startswith("*"):
                continue
            if not output_label(key, spec):
                missing.append(f"{name}.{key}")
    assert not missing, "这些输出接点会在界面上露出英文键名:" + ", ".join(missing)
