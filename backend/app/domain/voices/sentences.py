"""把转写引擎交来的段落切成「一句一行」—— 剪辑台的逐字稿、生成字幕和工作流的生成字幕**同一套断句**。

前端的那份是 `frontend/src/domain/timeline/transcriptProjection.ts` 的 transcriptSegmentsForEditing;两份由
`contracts/transcript-sentence-cases.json` 钉住(后端 tests/test_transcript_sentence_parity.py、前端
transcriptProjection.parity.test.ts 跑同一份语料)。改断句规则时先改语料,看着两侧一起红,再改两侧实现。

此前工作流的「生成字幕」直接拿引擎的段落当字幕:一段动辄二三十秒、上百个字,而同一份逐字稿在剪辑台上
是一句一行 —— 同一个视频,两个入口铺出来的字幕不一样。

规则(和前端逐字一致):
- 有词级时间戳:按词累加,遇到句末标点、停顿 ≥ 0.75 秒、一行满 8 秒、满 48 个显示单位(中日韩字算 2)、
  或满 28 个单位且遇到逗号类标点,就断一行。词的时间戳里常常没有标点,先把段落原文里的分隔符(含英文空格)
  补回到前一个词上。
- 没有词级时间戳:按句末标点切,时间按每句的显示单位数在段落里按比例分。ASCII 句号后面要跟空白(挡住 `3.5`),
  中文句号直接切。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Token:
    start_time: float
    end_time: float
    text: str


@dataclass(frozen=True)
class Segment:
    id: str
    start_time: float
    end_time: float
    text: str
    speaker: str | None = None
    tokens: tuple[Token, ...] = field(default_factory=tuple)


_CLOSERS = "\"'”’）)\\]"
_SENTENCE_END = re.compile(rf"[.!?。！？…][{_CLOSERS}]*\s*$")
_SOFT_PUNCTUATION = re.compile(rf"[,，;；:：、][{_CLOSERS}]*\s*$")
_FALLBACK_PARTS = re.compile(r"""(?:.*?(?:[.!?](?:["'”’」』）)\]]+)?(?:\s+|$(?![\s\S]))|[。！？…](?:["'”’」』）)\]]+)?)|.+$(?![\s\S]))""")
MAX_SENTENCE_SECONDS = 8
MAX_SENTENCE_UNITS = 48
SOFT_BREAK_UNITS = 28
PAUSE_BREAK_SECONDS = 0.75
_CJK_NAMES = ("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH", "HIRAGANA", "KATAKANA", "HANGUL")


def _is_cjk(character: str) -> bool:
    return unicodedata.name(character, "").startswith(_CJK_NAMES)


def display_units(text: str) -> int:
    """一行有多「宽」:空白不算,中日韩字算 2,其余算 1。"""
    return sum(0 if character.isspace() else 2 if _is_cjk(character) else 1 for character in text)


def _restore_token_formatting(tokens: list[Token], segment_text: str) -> list[Token]:
    """词的时间戳里常常没有标点:把段落原文里的分隔符(含英文空格)补到前一个词上。对不上就原样返回。"""
    source = segment_text.strip()
    if not tokens or not source:
        return tokens
    searchable = source.lower()
    restored = [replace(token, text=token.text.strip()) for token in tokens]
    cursor = 0
    for index, token in enumerate(restored):
        needle = token.text.lower()
        if not needle:
            return tokens
        position = searchable.find(needle, cursor)
        if position < cursor:
            return tokens
        separator = source[cursor:position]
        if separator:
            if index > 0:
                restored[index - 1] = replace(restored[index - 1], text=restored[index - 1].text + separator)
            else:
                restored[index] = replace(token, text=f"{separator}{token.text}")
        cursor = position + len(needle)
    trailing = source[cursor:]
    if trailing:
        restored[-1] = replace(restored[-1], text=restored[-1].text + trailing)
    return restored


def _fallback_paragraph(segment: Segment) -> list[Segment]:
    parts = [part.strip() for part in _FALLBACK_PARTS.findall(segment.text) if part.strip()]
    if len(parts) <= 1:
        return [segment]
    weights = [max(1, display_units(part)) for part in parts]
    total = sum(weights)
    duration = segment.end_time - segment.start_time
    rows: list[Segment] = []
    consumed = 0
    for index, text in enumerate(parts):
        start = segment.start_time + duration * (consumed / total)
        consumed += weights[index]
        end = segment.end_time if index == len(parts) - 1 else segment.start_time + duration * (consumed / total)
        rows.append(replace(segment, id=f"{segment.id}:{index}", start_time=start, end_time=end, text=text))
    return rows


def sentences_for_editing(segments: list[Segment]) -> list[Segment]:
    """引擎的段落 → 一句一行。见模块说明。"""
    rows: list[Segment] = []
    for segment in segments:
        ordered = sorted(
            (token for token in segment.tokens if token.end_time > token.start_time and token.text.strip()),
            key=lambda token: token.start_time,
        )
        if not ordered:
            rows.extend(_fallback_paragraph(segment))
            continue
        tokens = _restore_token_formatting(ordered, segment.text)
        lines: list[tuple[list[Token], str]] = []
        row: list[Token] = []
        text = ""
        for index, token in enumerate(tokens):
            row.append(token)
            text += token.text
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            duration = token.end_time - row[0].start_time
            pause = following.start_time - token.end_time if following else 0.0
            units = display_units(text)
            if (
                following is None
                or _SENTENCE_END.search(text)
                or pause >= PAUSE_BREAK_SECONDS
                or duration >= MAX_SENTENCE_SECONDS
                or units >= MAX_SENTENCE_UNITS
                or (units >= SOFT_BREAK_UNITS and _SOFT_PUNCTUATION.search(text))
            ):
                if row and text.strip():
                    lines.append((row, text.strip()))
                row, text = [], ""
        if len(lines) <= 1:
            rows.append(replace(segment, tokens=tuple(tokens), text=segment.text.strip() or (lines[0][1] if lines else "")))
            continue
        for index, (line_tokens, line_text) in enumerate(lines):
            rows.append(replace(
                segment,
                id=f"{segment.id}:{index}",
                start_time=segment.start_time if index == 0 else line_tokens[0].start_time,
                end_time=segment.end_time if index == len(lines) - 1 else line_tokens[-1].end_time,
                text=line_text,
                tokens=tuple(line_tokens),
            ))
    return rows
