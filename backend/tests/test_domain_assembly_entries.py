"""切片是实现细节,装配入口是公共 Interface。

ORM 和 schema 都按领域切在 `app/db/model_slices/` 与 `app/api/schemas/` 下,而调用方一律只从
`app.db.models` / `app.api.schemas` 取。这样继续切文件、或者把某个域从一个切片挪到另一个,
都不会扩散到全仓的 import 里(见 docs/ARCHITECTURE.md)。

**此前这里是二十条逐域手写的断言** —— 每切一个新域要补两条,而漏补的那一条不会报错:
它只是没人在看。切完最后一个域之后换成三条通用不变量,新切片自动被覆盖:

  1. 两个装配入口里**不定义任何东西**(一旦开始长自己的类,它就又变回了半个入口);
  2. 每个切片导出的每个类,都能从装配入口按**同一个身份**拿到(不是同名的另一个类);
  3. 每个 ORM 类都真的注册进了 `Base.metadata`(没注册的表 create_all 不会建,
     而它的行看起来一切正常,直到第一次查询报「no such table」)。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import importlib
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
ENTRIES = {
    "app.db.models": BACKEND / "app/db/models.py",
    "app.api.schemas": BACKEND / "app/api/schemas/__init__.py",
}
SLICE_DIRS = {
    "app.db.model_slices": BACKEND / "app/db/model_slices",
    "app.api.schemas": BACKEND / "app/api/schemas",
}
#: 不是切片:装配入口自己,以及 schema 的共用基类。
NOT_A_SLICE = {"__init__", "base", "model_base"}


def _slices() -> list[tuple[str, list[str]]]:
    found = []
    for package, directory in SLICE_DIRS.items():
        for path in sorted(directory.glob("*.py")):
            if path.stem in NOT_A_SLICE:
                continue
            exported = [node.name for node in ast.parse(path.read_text()).body if isinstance(node, ast.ClassDef)]
            if exported:
                found.append((f"{package}.{path.stem}", exported))
    return found


def _entry_for(module: str) -> str:
    return "app.db.models" if module.startswith("app.db.") else "app.api.schemas"


@pytest.mark.parametrize("name, path", sorted(ENTRIES.items()))
def test_装配入口里不定义任何东西(name: str, path: pathlib.Path) -> None:
    defined = [
        node.name
        for node in ast.parse(path.read_text()).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert defined == [], f"{name} 又开始自己定义东西了({defined}) —— 它只该转发切片"


@pytest.mark.parametrize("module, exported", _slices(), ids=lambda value: value if isinstance(value, str) else "")
def test_切片导出的每个类都能从装配入口拿到(module: str, exported: list[str]) -> None:
    sliced = importlib.import_module(module)
    entry = importlib.import_module(_entry_for(module))
    for name in exported:
        assert getattr(entry, name, None) is getattr(sliced, name), \
            f"{name} 在 {module} 里定义,却没从 {_entry_for(module)} 转发出去(或转发的是另一个同名类)"


def test_每个_ORM_类都注册进了_metadata() -> None:
    from app.db import models

    for module, exported in _slices():
        if not module.startswith("app.db."):
            continue
        sliced = importlib.import_module(module)
        for name in exported:
            table = getattr(sliced, name).__table__
            assert models.Base.metadata.tables.get(table.name) is table, f"{name} 没进 metadata"


def test_这道棘轮扫得到东西() -> None:
    """切片目录写错了会让这条测试永远绿 —— 一条永远绿的棘轮比没有更糟。"""
    found = _slices()
    assert len(found) >= 30, f"只扫到 {len(found)} 个切片,目录八成写错了"
    assert sum(len(names) for _, names in found) >= 250
