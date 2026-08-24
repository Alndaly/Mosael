"""外部命令只从一个口子出去。

这个仓库反复吃的亏是"同一件事有两份实现",而外部命令曾经有 35 份:各自裸调 `subprocess.run`,
于是各自都没有日志、各自把带 ANSI 颜色码的 stderr 端到界面上、各自不记耗时。补一遍容易,
**让它保持只有一份**才是这条测试的用处。

新增一处直接 `subprocess.run` 时这条会红。要么改用 `run_logged`,要么在下面的豁免名单里
写清楚为什么它不能走那条路。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib

#: 允许直接调用的地方,以及原因。
ALLOWED = {
    "app/core/child_process.py": "它就是那个口子本身",
}


def test_subprocess_run_only_happens_in_one_place() -> None:
    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        rel = str(path)
        if rel in ALLOWED:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        "这些地方绕开了 run_logged,于是没有日志、没有耗时、stderr 带着颜色码进界面:\n  "
        + "\n  ".join(offenders)
    )


def test_the_allowlist_does_not_quietly_grow() -> None:
    """豁免要少而有名有姓 —— 一张越写越长的名单等于没有名单。"""
    assert len(ALLOWED) <= 2, f"豁免名单在变长:{sorted(ALLOWED)}"
