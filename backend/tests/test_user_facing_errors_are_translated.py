"""棘轮:后端报给人看的错误**不写死中文句子**。

领域错误用 `core.i18n.LocalizedError(key, **params)`,路由里直接写的 `HTTPException(detail=…)`
用 `core.i18n.tr(key, **params)`。两者都按**这次请求**的语言翻(中间件把 Accept-Language 放进
ContextVar)。写死的中文在英文界面里原样弹出来 —— Blender 互通的报错就是这么被发现的:半句
中文、半句上游透传的英文。

扫的是 `raise …(`、`HTTPException(`、`detail=` 所在的行里有没有中文字符。`LEFT` 是存量,
**只减不增**:哪个文件翻完了就把它从这里删掉(或把数字改小),棘轮前进一格。

看不见的:句子拼在别的变量里再 raise、或者跨了几行的字符串。所以这是**下限**。
"""
from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import re
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
CJK = re.compile(r"[一-鿿]")
ERROR_LINE = re.compile(r"\braise \w[\w.]*\(|HTTPException\(|\bdetail=")


def _count() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in APP.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0] if not line.lstrip().startswith(("'", '"')) else line
            if ERROR_LINE.search(code) and CJK.search(code):
                found[str(path.relative_to(APP))] += 1
    return found


#: 还没翻完的:文件 → 还剩几行。**只减不增。**
LEFT: dict[str, int] = {
    "domain/blender/worker.py": 5,
}


def test_没有新的写死中文的报错() -> None:
    now = _count()
    grown = {f: (LEFT.get(f, 0), n) for f, n in now.items() if n > LEFT.get(f, 0)}
    assert not grown, (
        "这些文件的报错里多出了写死的中文(存量 → 现在)。用 LocalizedError / tr 加一个文案 key:\n  "
        + "\n  ".join(f"{f}: {a} → {b}" for f, (a, b) in sorted(grown.items()))
    )


def test_存量只减不增() -> None:
    now = _count()
    stale = {f: (n, now.get(f, 0)) for f, n in LEFT.items() if now.get(f, 0) < n}
    assert not stale, (
        "这些文件已经翻掉了一些,把 LEFT 里的数字改小(0 就删掉那一行),让棘轮前进一格:\n  "
        + "\n  ".join(f"{f}: {a} → {b}" for f, (a, b) in sorted(stale.items()))
    )
