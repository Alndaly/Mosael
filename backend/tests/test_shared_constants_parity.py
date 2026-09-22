"""共享常量契约:跑 contracts/shared-constants.json。

这一份和别的契约不同 —— 它没有"语料驱动两个实现"那么复杂,要钉的只是**几个数字/字符串在
两三个运行时里必须相等**。所以这条测试直接去源码里把它们读出来比对:契约里已经写明了每个
常量在哪个文件、叫什么名字。

为什么值得单独钉:这两个不一致时**都不会报错**,只会悄悄错开。

- `publish_partition_prefix`:两边拼的是同一个磁盘目录。改了其中一个,所有已登录发布账号的
  cookie 凭空消失,用户得把每个平台重新登录一遍。
- `embed_header_height_px`:Electron 按它定内嵌视图的边界,前端按它定那条工具栏的高度。
  不等就露出一条缝,缝里是 App 自己的顶栏 —— 看着像画面穿帮,而不像 bug。

Python 侧的值用 import 拿(那是真正跑的那个);TS/Electron 侧没有 Python 能直接执行的入口,
所以按契约里记的 `symbol` 从源码里取字面量。取不到就报错,**不是跳过** —— 一条悄悄跳过的
契约测试比没有更糟。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_CONTRACT = REPO / "contracts" / "shared-constants.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _constants() -> list[dict]:
    return _load()["constants"]


def _ids() -> list[str]:
    return [item["name"] for item in _constants()]


def _literal_from_source(path: Path, symbol: str) -> str:
    """从源码里取 `symbol = <字面量>`。TS 和 Python 的写法都能覆盖。"""
    source = path.read_text(encoding="utf-8")
    pattern = rf"\b{re.escape(symbol)}\s*(?::[^=\n]+)?=\s*([^;\n]+)"
    match = re.search(pattern, source)
    assert match, f"{path} 里找不到 {symbol} 的定义 —— 契约记的位置过期了"
    return match.group(1).strip().rstrip(";").strip()


def _as_value(literal: str) -> object:
    text = literal.strip()
    if text.startswith(('"', "'")):
        return text[1:-1]
    text = text.replace("_", "")  # TS 里的 10_000
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            continue
    return text


def test_contract_file_is_present_and_versioned() -> None:
    assert _CONTRACT.is_file(), f"共享常量契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "shared-constants"
    assert data["constants"], "语料为空 = 没有任何一致性保护"


@pytest.mark.parametrize("constant", _constants(), ids=_ids())
def test_every_runtime_agrees(constant: dict) -> None:
    expected = constant["value"]
    for impl in constant["implementations"]:
        path = REPO / impl["location"]
        assert path.is_file(), f"{constant['name']}:契约记的位置不存在了 —— {impl['location']}"
        actual = _as_value(_literal_from_source(path, impl["symbol"]))
        assert actual == expected, (
            f"{constant['name']} 在 {impl['runtime']}({impl['location']})里是 {actual!r},"
            f"契约说是 {expected!r}\n  为什么要紧:{constant['why']}"
        )


#: 单位 → 换算成秒的系数。预算写在各自运行时惯用的单位里(TS 用毫秒),比较之前先对齐。
_TO_SECONDS = {"s": 1.0, "ms": 0.001}


def _budgets() -> list[dict]:
    return _load().get("budgets", [])


def _budget_ids() -> list[str]:
    return [item["name"] for item in _budgets()]


def _seconds(side: dict) -> float:
    path = REPO / side["location"]
    assert path.is_file(), f"契约记的位置不存在了 —— {side['location']}"
    value = _as_value(_literal_from_source(path, side["symbol"]))
    assert isinstance(value, (int, float)), (
        f"{side['location']} 的 {side['symbol']} 读出来是 {value!r} —— 预算必须是个字面量数字,"
        "否则这条契约读不到它(提成具名常量就是为了这个)"
    )
    return float(value) * _TO_SECONDS[side["unit"]]


def test_有预算这一节() -> None:
    """跨进程的时间预算此前**一条都不在契约里** —— 它们只以注释的形式写在其中一侧。

    常量那一节说的是「两边必须相等」,而时间预算的关系是「一边必须装得下另一边」。
    两者错开时同样没有任何报错,只是等待在两侧的含义悄悄不同。
    """
    assert len(_budgets()) >= 4, "budgets 一节空了或缩水了 —— 那正是这条契约要防的"


@pytest.mark.parametrize("budget", _budgets(), ids=_budget_ids())
def test_内层预算装得进外层(budget: dict) -> None:
    assert budget["rule"] == "less_than", f"还不认识的关系:{budget['rule']}"
    inner, outer = _seconds(budget["inner"]), _seconds(budget["outer"])
    assert inner < outer, (
        f"{budget['name']}:内层 {budget['inner']['symbol']} = {inner}s,"
        f"外层 {budget['outer']['symbol']} = {outer}s —— 内层必须更短。\n"
        f"  为什么要紧:{budget['why']}"
    )


def test_python_side_is_read_by_import_not_only_by_regex() -> None:
    """正则读的是源码,import 读的是**真正跑的那个** —— Python 侧两条都要对得上。"""
    from app.core.db import PARTITION_PREFIX

    wanted = next(item for item in _constants() if item["name"] == "publish_partition_prefix")
    assert PARTITION_PREFIX == wanted["value"]
