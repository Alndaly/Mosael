"""断句契约的后端一侧:跑 contracts/transcript-sentence-cases.json。

前端 `transcriptProjection.parity.test.ts` 跑**同一份文件**。剪辑台的逐字稿 / 生成字幕和工作流的生成字幕
必须切得一样;改规则时先改语料,看着两侧一起红,再改两侧实现。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.voices.sentences import Segment, Token, sentences_for_editing

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "transcript-sentence-cases.json"


def _cases() -> list[dict]:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))["cases"]


def test_contract_file_is_present_and_versioned() -> None:
    data = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    assert data["contract"] == "transcript-sentences"
    assert isinstance(data["version"], int)
    assert data["cases"]


@pytest.mark.parametrize("case", _cases(), ids=[case["name"] for case in _cases()])
def test_sentences_match_contract(case: dict) -> None:
    segments = [
        Segment(id=s["id"], start_time=s["start_time"], end_time=s["end_time"], text=s["text"],
                tokens=tuple(Token(**token) for token in s["tokens"]))
        for s in case["segments"]
    ]
    actual = [
        {"id": row.id, "start_time": round(row.start_time, 6), "end_time": round(row.end_time, 6), "text": row.text}
        for row in sentences_for_editing(segments)
    ]
    assert actual == case["expected"], case["why"]
