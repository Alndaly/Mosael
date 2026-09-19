"""棘轮:节点**声明的输出**和执行体**真正返回的键**是同一批。

两个方向都会出事,而且都不报错:

- 声明了没返回 → 下游连上去、跑起来拿到的是空;
- 返回了没声明 → 界面上连不到它。`ai_generate` 就是这样:它一直在返回 `asset_ids`
  (一次生成的全部图),执行体的注释还写着「只往下游传第一张的话,其余的就没人看得见」,
  而 outputs 里没有它 —— 于是那句注释描述的正是当时的实际行为。

判据走 AST,只看**字面量 return**;经 helper 拼出来的那几个(note_read 把 read_reference 的
整份结果摊开)在 INDIRECT 里逐个写明理由。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

EXECUTORS = pathlib.Path(__file__).resolve().parents[1] / "app" / "domain" / "workflows" / "executors"

#: 返回值不是字面量字典的节点。**只减不增**,每条写明它的输出契约在哪。
INDIRECT = {
    # 把 notes.read_reference 的整份结果摊开(键由那个函数定),见 tests/test_notes.py。
    "note_read",
    # 返回 domain/scenes.render_shot_references 的结果(接口和智能体工具共用那一份),
    # 键由 tests/test_scene_workflow_nodes.py 钉着。
    "scene_render",
    # 循环/子图:输出是子图跑出来的东西,形状由体内的 output 节点决定。
    "loop_foreach",
    "loop_while",
    "subgraph",
    "call_workflow",
    # 插件节点的输出由插件清单声明(domain/plugins/nodes.node_meta)。
    "plugin_tool",
    # 输出就是用户在 start 上声明的那些参数 —— 形状由那张图自己定。
    "start",
    # 输出是那段代码 return 的东西(沙箱里跑),形状由写代码的人定。
    "code",
    # 在 run_http 里拼:同一份实现给节点和沙箱两条路用,键在那儿。
    "http_request",
}


def _executors() -> dict[str, ast.FunctionDef]:
    found: dict[str, ast.FunctionDef] = {}
    for path in sorted(EXECUTORS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for decorator in fn.decorator_list:
                if isinstance(decorator, ast.Call) and getattr(decorator.func, "id", "") == "register":
                    for arg in decorator.args:
                        if isinstance(arg, ast.Constant):
                            found[arg.value] = fn
    return found


def _own_returns(fn: ast.AST) -> list[ast.Return]:
    """**这个函数自己**的 return —— 不含体内定义的小助手(它们返回的是别的东西)。"""
    found: list[ast.Return] = []

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return):
                found.append(child)
            walk(child)

    walk(fn)
    return found


def _dict_keys(node: ast.AST | None, fn: ast.AST) -> set[str] | None:
    """一个 return 值里的键。字面量直接读;`return nothing` 这种就去找那个名字的字面量赋值
    (加上后来 `result["json"] = …` 的补写)—— 为了一条断言把代码改成到处重复字面量,
    换的是更差的代码。"""
    if isinstance(node, ast.Dict):
        if any(key is None for key in node.keys):  # {**something}
            return None
        return {key.value for key in node.keys if isinstance(key, ast.Constant)}
    if not isinstance(node, ast.Name):
        return None
    keys: set[str] | None = None
    for assigned in ast.walk(fn):
        if isinstance(assigned, (ast.Assign, ast.AnnAssign)):
            targets = assigned.targets if isinstance(assigned, ast.Assign) else [assigned.target]
            if len(targets) != 1:
                continue
            target = targets[0]
            if isinstance(target, ast.Name) and target.id == node.id:
                found = _dict_keys(assigned.value, fn)
                if found is None:
                    return None
                keys = found if keys is None else keys | found
            #: 之后补写进去的键(`result["json"] = …`)也是这个节点的输出。
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == node.id
                and isinstance(target.slice, ast.Constant)
            ):
                keys = (keys or set()) | {target.slice.value}
    return keys


def _returned_keys(fn: ast.AST) -> set[str] | None:
    """这个执行体交出去的那些键;拼不出来就返回 None(交给 INDIRECT 说明)。"""
    keys: set[str] = set()
    literal = False
    for node in _own_returns(fn):
        if node.value is None:
            continue
        found = _dict_keys(node.value, fn)
        if found is None:
            return None
        keys |= found
        literal = True
    return keys if literal else None


def test_声明的输出就是执行体返回的那些() -> None:
    from app.domain.workflows import NODE_TYPES

    mismatched: list[str] = []
    checked = 0
    for name, fn in sorted(_executors().items()):
        if name in INDIRECT or name not in NODE_TYPES:
            continue
        returned = _returned_keys(fn)
        if returned is None:
            mismatched.append(f"{name}:返回值不是字面量字典,要么改成字面量,要么写进 INDIRECT 并说明")
            continue
        checked += 1
        declared = set(NODE_TYPES[name].get("outputs") or [])
        if declared - returned:
            mismatched.append(f"{name}:声明了却没返回 {sorted(declared - returned)}")
        if returned - declared:
            mismatched.append(f"{name}:返回了却没声明 {sorted(returned - declared)} —— 下游连不到它")
    assert checked >= 20, "扫描没扫到东西,多半是 register 改了名字"
    assert not mismatched, "\n".join(mismatched)
