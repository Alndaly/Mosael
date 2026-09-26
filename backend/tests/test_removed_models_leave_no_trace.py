"""撤掉的模型不留残影:代码里不再有它们的 id、档案名和 Adapter。

撤掉一家的一种能力(MiniMax 音乐,ADR 0022 的补充)时,容易删掉 Adapter 和目录行、却漏下一处 —— 一份指着
它的能力档案、预设里的一个能力 id、界面上一句提示、智能体说明里的一个例子。漏下的那处不会报错,只会让用户
又看见一个选了必然失败的东西。存着的数据由迁移清(`remove-minimax-music-models`),迁移本身和它的测试、
以及说明「为什么撤掉」的文档,是唯一可以提到这些名字的地方。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 撤掉的东西 → 认它的写法。
REMOVED = {
    "MiniMax 音乐": re.compile(
        r"music-3\.0|music-2\.6|music-cover|minimax-music|MiniMaxMusic|MINIMAX_MUSIC|adapters[./]minimax[./]music"
    ),
}

#: 扫这些地方的源码。文档不扫:ADR 与能力矩阵要记下「接过、为什么撤」。
SCANNED = ("backend/app", "backend/mcp_server.py", "frontend/src", "agent-sidecar/src", "plugins", "contracts")
SUFFIXES = {".py", ".ts", ".tsx", ".json", ".mjs", ".cjs"}
#: 清存量数据的迁移要点名它清的是什么;生成的接口类型跟着 openapi 走。
ALLOWED = {"backend/app/db/migrations.py"}
SKIPPED_PARTS = {"node_modules", "generated", "dist", "__pycache__"}


def _sources() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for entry in SCANNED:
        path = ROOT / entry
        if path.is_file():
            found.append(path)
            continue
        for one in path.rglob("*"):
            if one.suffix in SUFFIXES and one.is_file() and not SKIPPED_PARTS & set(one.parts):
                found.append(one)
    return found


def test_撤掉的模型在代码里没有残影() -> None:
    sources = _sources()
    assert len(sources) > 100, "扫描范围不对:一个源文件都没扫到,这条测试就什么都没守"
    leftovers: list[str] = []
    for path in sources:
        relative = path.relative_to(ROOT).as_posix()
        if relative in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in REMOVED.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                leftovers.append(f"{relative}:{line} 还提到 {name}({match.group()})")
    assert not leftovers, "\n".join(leftovers)
