"""口癖词表的后端一侧:跑 contracts/filler-word-cases.json。

前端剪辑台的「一键去口癖」(transcriptProjection.ts 的 FILLER_CATEGORIES / fillerCategory)跑同一份语料,见
fillerWords.parity.test.ts。两边各写一份而不对账的话:面板上认得的「就是说」,口播整理交给模型时却没有时间,删不掉;或者反过来。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.voices.fillers import FILLER_CATEGORIES, filler_category, filler_spans

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

CORPUS = json.loads((Path(__file__).resolve().parents[2] / "contracts/filler-word-cases.json").read_text())


def test_词表和语料逐字一致() -> None:
    assert [
        {"id": one["id"], "ambiguous": one["ambiguous"], "words": list(one["words"])} for one in FILLER_CATEGORIES
    ] == CORPUS["categories"]


@pytest.mark.parametrize("case", CORPUS["cases"], ids=[repr(case["text"]) for case in CORPUS["cases"]])
def test_判一个词(case: dict) -> None:
    assert filler_category(case["text"]) == case["category"]


def test_中文逐字的_token_连起来认_长的优先_不重叠() -> None:
    """后端多走一步:中文的 token 一个字一个,「就是说」是三个 token,拼起来认。这一步只在后端(给模型的口头禅候选)。"""
    assert filler_spans(list("我们就是说来聊")) == [(2, 5)]
    assert filler_spans(list("这个那个东西")) == [(0, 4)], "「这个那个」整个是一项,不拆成「那个」"
    assert filler_spans(["So", "um", "I", "like", "it"]) == [(1, 2), (3, 4)]
    assert filler_spans(list("那天")) == []
