"""逐字稿变成**文字**的那几条规矩:交给模型整理时怎么压缩、剪掉几段之后剩下的话怎么接回去、词与词之间要不要补空格。

此前住在工作流执行器 `executors/subjobs.py` 里(那里只该管「这个节点跑什么」),而它们说的是逐字稿本身的事 ——
整理模板、剪辑台都会用到。搬到逐字稿领域,执行器只调。
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.transcripts.fillers import filler_spans


#: 段内两个词之间空了这么久才算「停顿」,值得把两边的词和它们的时间交给模型(整理模板的长停顿阈值默认 1 秒,
#: 这里放宽一些:阈值是模型按节点参数自己判的,这里只决定给不给它看)。
PAUSE_SECONDS = 0.6


#: 每个停顿前后各带几个词 —— 口头禅、错误起句多半就贴在停顿两边。
WORDS_AROUND_PAUSE = 2


def compact_timed_text(segments: list[dict[str, Any]]) -> str:
    """把逐字稿编码成交给 LLM 的紧凑 JSON:**段落级**的起止和正文(带标点),词级时间只给停顿附近的词和口头禅候选。

    此前每个词都带着起止时间整份嵌进提示词:20 分钟的口播约 11 万字,超出多数模型的上下文,整理模板在长素材上
    直接失败。模型要精确落刀的地方只有停顿和口头禅:段与段之间的停顿从相邻两段的起止就读得出;段内的停顿在 `pauses`
    里给出起止,并附上两边各几个词的时间(`tokens`);**口头禅候选**(transcripts/fillers 的口癖词表,和剪辑台「一键去口癖」
    同一张表)不管在不在停顿附近,都在 `fillers` 里给出起止和原文 —— 此前它们只在停顿附近才有时间,连续说话被 VAD 切成
    一整段时段里没有停顿,口头禅一个时间都没有,模型保守地一处都不删。`tokens` / `fillers` 的列顺序见顶层 `token_columns`。
    别处的重复、跑题按段落定位就够。

    段落正文不能省,而且照原样给(标点在):ASR token 常省略标点,偶尔还会缺少段尾。每段都写空 speaker 是冗余,省掉。
    """
    compact: list[dict[str, Any]] = []
    for segment in segments:
        row: dict[str, Any] = {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
        }
        if segment.get("speaker"):
            row["speaker"] = segment["speaker"]
        tokens = segment.get("tokens") if isinstance(segment.get("tokens"), list) else []
        pauses: list[list[float]] = []
        near: set[int] = set()
        for index in range(1, len(tokens)):
            gap_start, gap_end = float(tokens[index - 1]["end"]), float(tokens[index]["start"])
            if gap_end - gap_start >= PAUSE_SECONDS:
                pauses.append([gap_start, gap_end])
                near.update(range(max(0, index - WORDS_AROUND_PAUSE), min(len(tokens), index + WORDS_AROUND_PAUSE)))
        if pauses:
            row["pauses"] = pauses
            row["tokens"] = [[tokens[index]["start"], tokens[index]["end"], tokens[index]["text"]] for index in sorted(near)]
        spans = filler_spans([str(token.get("text") or "") for token in tokens])
        if spans:
            row["fillers"] = [
                [tokens[first]["start"], tokens[last - 1]["end"],
                 join_words([str(tokens[index].get("text") or "").strip() for index in range(first, last)])]
                for first, last in spans
            ]
        compact.append(row)
    return json.dumps(
        {"token_columns": ["start", "end", "text"], "segments": compact},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def kept_text(segments: list[dict[str, Any]], removed: list[tuple[float, float]]) -> str:
    """删掉这些范围之后,逐字稿还剩下什么 —— 按保留的原话拼出来,一个字不改,**标点照原文留**。

    此前这份「整理后的逐字稿」由模型在方案里全文复述(cleaned_verbatim):长素材上输出一长就被截断,而且复述
    不保证一字不差。有词级时间的段按词判(词的中点落在删除范围里就去掉),没有的整段判(整段在删除范围里才去掉)。

    按词删过的段,此前直接把剩下的词拼起来 —— ASR 的 token 多半不带标点,整理后的逐字稿就成了没有一个标点的一长串。
    现在把 token 一个个对回这段的正文,夹在它们之间的标点、空白照原文留(见 _kept_segment_text);对不上的才按词拼。
    """
    def gone(start: float, end: float) -> bool:
        middle = (start + end) / 2
        return any(cut_start <= middle <= cut_end for cut_start, cut_end in removed)

    lines: list[str] = []
    for segment in segments:
        try:
            start, end = float(segment.get("start") or 0), float(segment.get("end") or 0)
        except (TypeError, ValueError):
            continue
        tokens = [one for one in segment.get("tokens") or [] if isinstance(one, dict)]
        touched = any(cut_start < end and cut_end > start for cut_start, cut_end in removed)
        original = str(segment.get("text") or "").strip()
        if not touched:
            text = original
        elif tokens:
            dropped = [gone(float(one.get("start") or 0), float(one.get("end") or 0)) for one in tokens]
            words = [str(one.get("text") or "") for one in tokens]
            text = _kept_segment_text(original, words, dropped)
            if text is None:
                text = join_words([word.strip() for word, out in zip(words, dropped) if not out and word.strip()])
        else:
            text = "" if gone(start, end) else original
        if text:
            lines.append(text)
    return "\n".join(lines)


#: 句末的标点:一串被删的词收尾处的标点是不是该留下来(「今天很好嗯。」删掉「嗯」还该有句号)。
_SENTENCE_END = set("。！？!?.…")


def _kept_segment_text(text: str, words: list[str], dropped: list[bool]) -> str | None:
    """一段正文按词删过之后剩下的样子:token 对回正文的位置,保留的词连同它后面的标点、空白照原文。

    一串被删的词两边的标点怎么留:前一个保留的词后面有标点(「大家好,嗯,今天」)就用它;没有的话,只有被删的那串收尾处
    是句末标点(「很好嗯。」)才留那个;删到段尾时句末标点优先。原文两个西文词之间没有空格(有的引擎正文就是连写的)时,
    按 join_words 的规矩补一个。对不上(引擎的 token 和正文写法不一样,比如一个按数字、一个按读音)返回 None。
    """
    lowered = text.lower()
    if len(lowered) != len(text):
        lowered = text
    spans: list[tuple[int, int]] = []
    cursor = 0
    for word in words:
        needle = word.strip().lower()
        if not needle:
            spans.append((cursor, cursor))
            continue
        found = lowered.find(needle, cursor)
        if found < 0 or any(ch.isalnum() for ch in text[cursor:found]):
            return None
        spans.append((found, found + len(needle)))
        cursor = found + len(needle)
    if not spans or any(ch.isalnum() for ch in text[cursor:]):
        return None
    glue = [text[spans[index][1]:(spans[index + 1][0] if index + 1 < len(spans) else len(text))] for index in range(len(spans))]

    out = text[:spans[0][0]]
    previous: int | None = None
    index = 0
    while index < len(spans):
        if dropped[index]:
            run_end = index
            while run_end + 1 < len(spans) and dropped[run_end + 1]:
                run_end += 1
            if previous is not None:
                before, after = glue[previous], glue[run_end]
                to_end = run_end + 1 == len(spans)
                if to_end:
                    out += after if _SENTENCE_END & set(after) else before
                else:
                    out += before if before.strip() else (after if _SENTENCE_END & set(after) else before)
                previous = None
                if to_end:
                    return out.strip()
                out = _space_if_needed(out, text[spans[run_end + 1][0]:spans[run_end + 1][1]])
            index = run_end + 1
            continue
        word = text[spans[index][0]:spans[index][1]]
        if previous is not None:
            out += glue[previous]
            out = _space_if_needed(out, word)
        out += word
        previous = index
        index += 1
    if previous is not None:
        out += glue[previous]
    return out.strip()


def _space_if_needed(out: str, word: str) -> str:
    """接下一个词之前:前后都是西文、中间又没有任何分隔时补一个空格(规矩同 join_words)。"""
    if out and word and out[-1].isascii() and not out[-1].isspace() and out[-1] not in "([{'\"" \
            and word[0].isascii() and word[0].isalnum() and not (out[-1].isdigit() and word[0].isdigit()):
        return out + " "
    return out


def join_words(words: list[str]) -> str:
    """词级 token 拼回一句:**按相邻两个 token 判**要不要空格 —— 前一个以西文字母、数字或西文标点收尾,后一个以
    西文字母或数字开头,中间才空一格(`hello world`、`AI, right`);中文逐字的 token 之间、中英交界处都不空。

    此前按整段判:中文段里只要夹着一个英文词,整段每个字之间都插了空格(「今 天 我 们 用 AI」)。

    **数字挨着数字不空**:SenseVoice 把「92」逐位给成「9」「2」两个 token,空一格就成了「9 2度」。
    """
    out = ""
    for word in words:
        if out and out[-1].isascii() and not out[-1].isspace() and out[-1] not in "([{'\"" \
                and word[0].isascii() and word[0].isalnum() and not (out[-1].isdigit() and word[0].isdigit()):
            out += " "
        out += word
    return out
