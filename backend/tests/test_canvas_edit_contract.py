"""画布编辑指令的插件一侧:跑 contracts/canvas-edit-ops.json(主进程与桥那两侧见 electron/canvasEditOps.contract.test.ts)。

插件 canvas_edit 模拟智能体那一批改动,每一条照做之后用 `_record(交给桥的那条, 给人看的那条, layer)` 记下交给桥的指令 ——
那一条要原样过主进程的契约解析、再由桥照做。这里静态比对每一处 `_record` 拼的指令名与字段,不用等到真开一个工作台。
上限也比:插件放过的一批,主进程不该因为上限不同再拒。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS = json.loads((ROOT / "contracts/canvas-edit-ops.json").read_text(encoding="utf-8"))
SOURCE = ROOT / "plugins/bundled/comfyui/tools/canvas_edit.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def _literal_keys(node: ast.expr) -> dict[str, ast.expr] | None:
    """一个 dict 字面量里写出的键 → 值;`**({...} if … else {})` 这种条件展开也算上。不是字面量就 None。"""
    if not isinstance(node, ast.Dict):
        return None
    keys: dict[str, ast.expr] = {}
    for key, value in zip(node.keys, node.values):
        if isinstance(key, ast.Constant):
            keys[key.value] = value
        elif key is None and isinstance(value, ast.IfExp) and isinstance(value.body, ast.Dict):
            keys.update(_literal_keys(value.body) or {})
    return keys


def _recorded() -> list[tuple[int, str, set[str]]]:
    """每一处 `self._record(第一个参数, …)`:(行号, 指令名, 字段)。第一个参数是变量的,找同一个函数里给它赋的那个字面量。"""
    found = []
    for function in (node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef)):
        assigned = {
            target.id: node.value
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for call in ast.walk(function):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "_record"):
                continue
            first = call.args[0]
            literal = _literal_keys(assigned[first.id] if isinstance(first, ast.Name) else first)
            assert literal is not None, f"canvas_edit.py:{call.lineno} 交给桥的那条不是字面量,扫不到了"
            op = literal.get("op")
            assert isinstance(op, ast.Constant), f"canvas_edit.py:{call.lineno} 指令名不是字面量"
            found.append((call.lineno, op.value, set(literal)))
    return found


RECORDED = _recorded()


def test_scan_sees_every_instruction() -> None:
    assert {op for _line, op, _keys in RECORDED} == set(CORPUS["ops"]), "插件交给桥的指令与语料不一致(多了或少了一种)"


@pytest.mark.parametrize(("line", "op", "keys"), RECORDED, ids=[f"{op}@{line}" for line, op, _ in RECORDED])
def test_the_plugin_hands_the_bridge_only_what_the_contract_accepts(line: int, op: str, keys: set[str]) -> None:
    accepted = set(CORPUS["ops"][op]["fields"]) - {"layer"}  # layer 由 _record 统一补上
    assert keys <= accepted, f"canvas_edit.py:{line} 给 {op} 拼了契约外的字段:{sorted(keys - accepted)}"


def test_record_always_adds_the_layer() -> None:
    record = next(node for node in ast.walk(TREE) if isinstance(node, ast.FunctionDef) and node.name == "_record")
    assert '"layer": layer' in ast.unparse(record).replace("'", '"')


def test_limits_match_the_contract() -> None:
    constants = {
        target.id: node.value.value
        for node in TREE.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    limits = CORPUS["limits"]
    assert constants["MAX_OPS"] == limits["ops_per_batch"]
    assert constants["MAX_VALUE"] == limits["value_chars"]
    assert constants["MAX_COORDINATE"] == limits["coordinate"]
