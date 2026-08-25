"""FunASR 两种模型的输出形状不一样,转换必须都认。

线上翻车过:换到 SenseVoice 之后每一次转写都报「转写结果为空」。原因不是模型没识别 ——
它识别得好好的,是**句子的字段名不同**:Paraformer 给 `text`,SenseVoice 给 `sentence`。
只读前者时每句都取到空串,整条转写产出 0 段,而错误信息只说"结果为空",看不出是字段名对不上。

SenseVoice 还会把语种/情感/事件以特殊标记塞在文本开头(`<|zh|><|NEUTRAL|><|Speech|><|withitn|>`),
不剥掉就会直接出现在字幕里。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# worker 跑在**另一个解释器**里(那边才有 funasr),但这些函数是纯字符串处理,可以直接测。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "ai" / "runtime" / "workers"))
import asr as asr_worker  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "expected_text", "expected_lang"),
    [
        ("<|zh|><|NEUTRAL|><|Speech|><|withitn|>你真不错。", "你真不错。", "zh"),
        ("<|en|><|HAPPY|><|Speech|><|withitn|>Nice work.", "Nice work.", "en"),
        ("<|ja|><|NEUTRAL|><|Speech|><|woitn|>ありがとう", "ありがとう", "ja"),
        ("没有任何标记", "没有任何标记", ""),
    ],
)
def test_tags_are_stripped_and_language_recovered(raw: str, expected_text: str, expected_lang: str) -> None:
    """标记要剥掉,而**第一个标记正是检测出的语种** —— 比猜一个默认值准得多,而且下游
    (对齐、翻译、导出)都按它走。"""
    text, language = asr_worker.strip_funasr_tags(raw)
    assert text == expected_text
    assert language == expected_lang


def test_sensevoice_sentence_field_is_read() -> None:
    """**SenseVoice 的句子在 `sentence` 里**。只读 `text` 的那一版,这里会返回 0 段。"""
    segments = asr_worker.funasr_sentences_to_segments([
        {
            "start": 0,
            "end": 1540,
            "sentence": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你真不错。",
            "timestamp": [[90, 150], [270, 330], [510, 570], [690, 750]],
            "spk": 0,
        }
    ])
    assert len(segments) == 1
    assert segments[0]["text"] == "你真不错。"
    assert segments[0]["speaker"] == "SPEAKER_00"
    assert [w["word"] for w in segments[0]["words"]] == ["你", "真", "不", "错"]


def test_paraformer_text_field_still_works() -> None:
    """老字段不能因此失效:同一个函数要同时认两种模型的输出。"""
    segments = asr_worker.funasr_sentences_to_segments([
        {"start": 0, "end": 500, "text": "你好", "timestamp": [[0, 200], [200, 400]], "spk": 1}
    ])
    assert len(segments) == 1
    assert segments[0]["text"] == "你好"
    assert segments[0]["speaker"] == "SPEAKER_01"
