"""上游没报用量时的 token 估算。

**必须和桌面端 `app/core/token_estimate.py` 算出同一个数** —— 用户在应用里看到的用量、
本地账本记的花费、Cloud 实扣的积分,三处不能各说各话。语料在
`contracts/token-estimate-cases.json`,两侧测试各跑一遍;改算法先改语料。

只做计费回退,不是分词器:上游报了 usage 就一律以上游为准(`usage_reported=True`)。
"""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def estimate_text_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    cjk_chars = len(_CJK.findall(stripped))
    non_cjk = _CJK.sub("", stripped)
    non_cjk = re.sub(r"\s", "", non_cjk)
    return max(1, round(cjk_chars + len(non_cjk) / 4))
