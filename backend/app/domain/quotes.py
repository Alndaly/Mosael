"""模型写的报告里加了引号的话,逐条核对是不是取回来的原文;找不到的去掉引号、标为转述。

为什么要代码把关(2026-10,评论区洞察真跑 k3,409 / 423 条评论逐条对过):提示词里写明「引号里只放逐字摘录」之后,
报告里仍有加了「」的话在取回的评论里找不到 —— 归纳出来的一句、几条揉成的一个问题。读的人会把它当成观众的原话。

**什么算原文**:规范化之后是某一条原文的子串。规范化只抹掉不算改字的差别:全角 / 半角(NFKC,模型常把「，」写成
「,」)、空白和换行、B 站的表情码(`[笑哭]`,模型摘录时常顺手去掉)。用省略号删节的长评论,每一段按顺序都在
**同一条**原文里才算 —— 两条评论各取半句拼成一句不算。

只认「」和“”两种引号:书名号《》是标题,不是引用;英文直引号 "…" 在代码、数字里太常见,认它会误伤。
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.core.i18n import tr

_QUOTE = re.compile(r"「([^「」\n]+)」|“([^“”\n]+)”")
_ELLIPSIS = re.compile(r"…+|\.{3,}|⋯+")
_EMOTE = re.compile(r"\[[^\[\]\s]{1,24}\]")
_SPACE = re.compile(r"\s+")
#: 「找不到」的清单最多带多少条进输出(运行记录里看个大概就够)。
_UNMATCHED_SHOWN = 50


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return _SPACE.sub("", _EMOTE.sub("", text)).lower()


def _strings(value: Any) -> list[str]:
    """原文里所有的字:JSON(对象、列表,或一段 JSON 文字)里每一个字符串各算一条;普通文字整段算一条。"""
    if isinstance(value, dict):
        return [one for item in value.values() for one in _strings(item)]
    if isinstance(value, list):
        return [one for item in value for one in _strings(item)]
    if not isinstance(value, str) or not value.strip():
        return []
    text = value.strip()
    if text[0] in "[{":
        try:
            return _strings(json.loads(text))
        except ValueError:
            pass
    return [value]


def _in_order(pieces: list[str], text: str) -> bool:
    at = 0
    for piece in pieces:
        found = text.find(piece, at)
        if found < 0:
            return False
        at = found + len(piece)
    return True


@dataclass
class QuoteCheck:
    texts: dict[str, str]
    checked: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)

    @property
    def paraphrased(self) -> int:
        return self.checked - self.matched

    def summary(self) -> str:
        """写进取数说明的那一句。"""
        if not self.checked:
            return tr("quoteCheck_none")
        if not self.paraphrased:
            return tr("quoteCheck_allFound", checked=self.checked)
        return tr("quoteCheck_some", checked=self.checked, matched=self.matched, paraphrased=self.paraphrased)


def check_quotes(texts: dict[str, Any], sources: Any) -> QuoteCheck:
    """核对 `texts` 里每一段文字中加了引号的话;`sources` 是这些话该出自的原文(评论、标题、逐字稿……)。

    交回改写过的文字:找得到的原样留着,找不到的去掉引号、后面标「(转述)」。"""
    corpus = [_normalize(one) for one in _strings(sources)]
    mark = tr("quoteCheck_paraphrasedMark")
    result = QuoteCheck(texts={})

    def found(quote: str) -> bool:
        pieces = [piece for piece in (_normalize(part) for part in _ELLIPSIS.split(quote)) if piece]
        return not pieces or any(_in_order(pieces, one) for one in corpus)

    def rewrite(match: re.Match[str]) -> str:
        quote = match.group(1) or match.group(2)
        result.checked += 1
        if found(quote):
            result.matched += 1
            return match.group(0)
        if len(result.unmatched) < _UNMATCHED_SHOWN:
            result.unmatched.append(quote)
        return f"{quote}{mark}"

    for name, text in texts.items():
        result.texts[name] = _QUOTE.sub(rewrite, text if isinstance(text, str) else str(text or ""))
    return result
