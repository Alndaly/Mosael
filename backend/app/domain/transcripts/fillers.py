"""口癖词表:哪些词是口头禅,按类别。

和剪辑台逐字稿面板的那一份(frontend/src/domain/timeline/transcriptProjection.ts 的 FILLER_CATEGORIES)是**同一张表**,
由 contracts/filler-word-cases.json 钉着:面板上「一键去口癖」认得的词,和口播整理模板交给模型的口头禅候选是同一批。

类别的意思见前端那一份的说明:拖音几乎总是口癖;中文套话多半是;歧义词(中文「那个」、英文 like)大多数时候是正经词 ——
面板上默认不选,交给模型时照样算候选(模型看上下文判断),但不替它做决定。
"""

from __future__ import annotations

import re
from typing import Any

FILLER_CATEGORIES: tuple[dict[str, Any], ...] = (
    {"id": "hesitation", "ambiguous": False, "words": ("呃", "嗯", "唔", "um", "uh", "uhm", "er", "erm", "hmm")},
    {"id": "phrase", "ambiguous": False, "words": ("啊这", "这个那个", "就是说", "然后就是")},
    {"id": "ambiguousZh", "ambiguous": True, "words": ("那个",)},
    {"id": "ambiguousEn", "ambiguous": True, "words": ("like",)},
)

_CATEGORY_BY_WORD = {word: category["id"] for category in FILLER_CATEGORIES for word in category["words"]}
#: 判的时候去掉的标点 —— 和前端 fillerCategory 的那一组字符同一份。
_PUNCTUATION = re.compile(r"[，。！？、,.;:!?…]")
#: 最长的口癖词由几个字组成(中文逐字给的 token,「这个那个」是四个)。
MAX_FILLER_TOKENS = max(len(word) for word in _CATEGORY_BY_WORD)


def filler_category(text: str) -> str | None:
    """这个词是哪一类口癖;不是口癖就是 None。"""
    return _CATEGORY_BY_WORD.get(_PUNCTUATION.sub("", text.strip().lower()))


def filler_spans(words: list[str]) -> list[tuple[int, int]]:
    """一串连续的词里口癖候选所在的位置 `[(起, 止), ...]`(止不含)。

    中文的 token 多半一个字一个:「就是说」是三个 token。所以按**连续几个 token 拼起来**认,长的优先、不重叠。
    """
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(words):
        for size in range(min(MAX_FILLER_TOKENS, len(words) - index), 0, -1):
            if filler_category("".join(words[index:index + size])) is not None:
                spans.append((index, index + size))
                index += size
                break
        else:
            index += 1
    return spans
