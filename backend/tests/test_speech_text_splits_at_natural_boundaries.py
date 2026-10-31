"""念长文本前怎么切段(workers/f5_driver.split_for_synthesis)。

段长只影响念得好不好,不影响会不会崩 —— 所以这里钉的是「切得自然」:先句子、再分句、再词、最后才逐字;
英文不从单词中间断开;切完拼回去还是原文;每段都不超过上限。
"""
from __future__ import annotations

import pytest

from app.ai.runtime.workers.f5_driver import segment_budget, split_for_synthesis


def _bytes(text: str) -> int:
    return len(text.encode("utf-8"))


@pytest.mark.parametrize(
    ("text", "limit"),
    [
        ("今天天气很好。我们去公园散步吧！你觉得怎么样？" * 4, 60),
        ("这是一句非常非常长的话，中间只有逗号，没有句号，一直说下去，说到超过上限为止" * 2, 40),
        ("The quick brown fox jumps over the lazy dog and keeps running far away " * 3, 50),
        ("没有任何标点也没有空格的一长串中文字一直写下去直到超过上限" * 2, 30),
    ],
)
def test_every_segment_fits_and_nothing_is_lost(text: str, limit: int) -> None:
    segments = split_for_synthesis(text, limit)

    assert segments
    assert all(_bytes(segment) <= limit for segment in segments), segments
    assert "".join(segments).replace(" ", "") == text.replace(" ", "")


def test_sentences_are_packed_up_to_the_limit() -> None:
    segments = split_for_synthesis("一。二。三。四。", 12)

    assert segments == ["一。二。", "三。四。"]


def test_a_long_sentence_breaks_at_its_commas_first() -> None:
    segments = split_for_synthesis("前半句说了这些，后半句说了那些。", 30)

    assert segments == ["前半句说了这些，", "后半句说了那些。"]


def test_english_without_punctuation_never_splits_inside_a_word() -> None:
    text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"

    segments = split_for_synthesis(text, 20)

    words = set(text.split())
    assert all(set(segment.split()) <= words for segment in segments), segments


def test_short_text_stays_one_segment() -> None:
    assert split_for_synthesis("你好。", 80) == ["你好。"]


def test_blank_text_has_no_segments() -> None:
    assert split_for_synthesis("   ", 80) == []


def test_budget_follows_the_reference_speaking_rate_with_a_floor() -> None:
    # 5 秒参考说了 60 字节 → 12 字节/秒,剩 17 秒可念 → 204 字节。
    assert segment_budget(5.0, "这" * 20, 1.0) == 204
    assert segment_budget(5.0, "这" * 20, 0.5) == 102
    # 参考说得极慢、或者干脆没有文本:不会算出个位数上限。
    assert segment_budget(12.0, "这", 1.0) == 20
    assert segment_budget(0.0, "", 1.0) == 20
