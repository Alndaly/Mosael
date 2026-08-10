"""吞掉异常不许再变多。

**不能一刀切**:有些吞是对的 —— 统计目录大小时跳过一个读不动的文件、杀一个已经死了的进程、
清理临时文件失败。这些每一次都记一行日志,只会把真正要看的冲走(今天刚为访问日志做过同样
的取舍)。

不对的是另一类:**一件完整的事失败了,而没有任何地方留下痕迹**。今天有两个 bug 从这类地方
钻出来:KB 那个 `NameError` 藏在 except 里,整条增强索引一次都没跑过而没人看得出来;
挑设备失败时 `pass`,于是"为什么这么慢"在日志里没有线索(实际是从 MPS 掉回了 CPU)。

所以判据不是"零",是**这张名单不许变长**:每一处都得有名有姓、写清为什么它可以不出声。
新长出来一处,这条就红,写的人得回答"它属于哪一类"。
"""

from __future__ import annotations

import ast
import pathlib

#: (文件, 允许的处数) —— 每一处的理由写在下面。
ALLOWED = {
    # _dir_size 逐个文件 stat:一个读不动的文件跳过就好,每次记一行会淹掉真正的日志;
    # 外层那个已经记 debug 了(残缺的总量会被当判据用)。
    "app/audio/tts_models.py": 3,
    # 迁移前逐个引擎探测:探不动就试下一个,run_logged 已经记过命令与失败。
    "app/domain/tts_config.py": 1,
    # 合成失败的兜底:它自己会 logger.warning,这里数的是它里层的 rollback 分支。
    "app/audio/voices.py": 1,
    # kill 一个已经死了的进程。
    "app/audio/tts_daemon.py": 1,
}


def _silent_handlers(path: pathlib.Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = ast.Module(body=node.body, type_ignores=[])
        dumped = ast.dump(body)
        if "logger" in dumped or "print" in dumped:
            continue
        if any(isinstance(n, ast.Raise) for n in ast.walk(body)):
            continue
        found.append(node.lineno)
    return found


def test_the_silent_swallows_do_not_multiply() -> None:
    grown: list[str] = []
    for name, budget in ALLOWED.items():
        lines = _silent_handlers(pathlib.Path(name))
        if len(lines) > budget:
            grown.append(f"{name}: {len(lines)} 处(名单里写的是 {budget})→ 第 {lines} 行")
    assert not grown, (
        "克隆这条路上又长出了不出声的 except。它属于哪一类?\n"
        "  逐项跳过 → 补进 ALLOWED 并写清理由\n"
        "  整件事失败 → 记日志或重抛\n  " + "\n  ".join(grown)
    )


def test_the_budget_is_not_padded() -> None:
    """名单只减不增才有意义 —— 这条盯着别人把预算调大了事。

    真要新增一处合理的吞,改这个数是**明确的动作**,会出现在 diff 里被看见。
    """
    assert sum(ALLOWED.values()) <= 6, f"预算总数在变大:{ALLOWED}"
