"""结构性约束:`ai/runtime/workers/` 下的脚本**不许 import app.***。

它们不在后端进程里跑,而是被引擎自己的 venv 起成子进程(`python workers/tts.py …`)。
那个解释器的 sys.path 上**没有本仓库** —— import 会在运行时炸。

而这类错误单测抓不到:workers 在测试里从来不被 import,所以静态上看一切正常。用户那边的
表现是"点了合成,转半天,然后一句看不懂的 ModuleNotFoundError"。

这条规则此前只写在目录说明里。写在注释里的规则,是下一个人在赶时间时最先违反的那一类 ——
他会想"就 import 一个常量而已"。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import pathlib

from app.ai.runtime import workers

WORKERS = pathlib.Path(__file__).resolve().parents[1] / "app" / "ai" / "runtime" / "workers"


def _modules() -> list[pathlib.Path]:
    return [p for p in sorted(WORKERS.glob("*.py")) if p.name != "__init__.py"]


def _entry_scripts() -> tuple[pathlib.Path, ...]:
    """入口由 workers 包公开声明；共享模块可以与入口脚本放在同一运行时边界内。"""
    return (workers.asr_script(), workers.tts_script())


def test_worker不认识本仓库() -> None:
    offenders: list[str] = []
    for path in _modules():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if name == "app" or name.startswith("app."):
                    offenders.append(f"{path.name}:{node.lineno}  {name}")

    assert offenders == [], (
        "worker 由**引擎自己的 venv**跑,那个解释器的 sys.path 上没有本仓库 —— "
        "import 会在用户机器上炸,而测试里抓不到(它们从不被 import):\n  " + "\n  ".join(offenders)
    )


def test_worker是能独立跑的脚本() -> None:
    """公开声明的入口必须可独立运行；协议等共享模块不应伪装成入口。"""
    for path in _entry_scripts():
        source = path.read_text(encoding="utf-8")
        assert "__main__" in source, f"{path.name} 被声明为 worker 入口却没有 __main__"


def test_目录不是空的() -> None:
    """扫描类的检查最怕"没东西可扫所以通过"。上一次改判据时就出过这个假绿。"""
    assert _modules(), "workers/ 空了 —— 要么真没有了(那这条测试该删),要么路径写错了"
    assert all(path in _modules() for path in _entry_scripts()), "公开入口必须位于受约束的 workers/ 边界内"
