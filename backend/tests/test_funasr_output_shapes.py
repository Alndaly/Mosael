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


def test_sensevoice_spans_follow_its_own_tokens_not_the_characters() -> None:
    """**SenseVoice 给每个 token 一个时间,标点也算一个 token;英文的 token 是词,不是字母。**

    实测(本机 SenseVoiceSmall):「大家好，嗯，…」120 个 token 里 13 个是标点,各带一段时间;
    此前按「去掉标点的字」逐个配时间,每过一个标点就错开一位 —— 30 秒的口播到结尾错开十几个字
    (两三秒),字幕、剪口头禅的范围全跟着偏。英文更糟:44 个词的时间被配给了前 44 个字母,
    逐字稿的词级时间变成 `W`、`e`、`l`……,后半句一个时间都没有。

    时间和 token 的对应关系在结果的 `words` 里(和各句 timestamp 首尾相接、一一对应),照它配。
    """
    sentences = [
        {"start": 0, "end": 1500, "sentence": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>你好，世界。",
         "timestamp": [[0, 100], [100, 200], [200, 300], [300, 400], [400, 500], [500, 600]], "spk": 0},
        {"start": 2000, "end": 3500, "sentence": "<|en|><|NEUTRAL|><|Speech|><|withitn|>Hello world, 92.",
         "timestamp": [[2000, 2400], [2400, 2800], [2800, 2850], [2900, 3000], [3000, 3100], [3100, 3150]], "spk": 0},
    ]
    words = ["你", "好", "，", "世", "界", "。", "Hello", "world", ",", "9", "2", "."]
    segments = asr_worker.funasr_sentences_to_segments(sentences, words=words)
    assert [(w["word"], w["start"]) for w in segments[0]["words"]] == [("你", 0.0), ("好", 0.1), ("世", 0.3), ("界", 0.4)]
    assert [(w["word"], w["start"], w["end"]) for w in segments[1]["words"]] == [
        ("Hello", 2.0, 2.4), ("world", 2.4, 2.8), ("9", 2.9, 3.0), ("2", 3.0, 3.1),
    ]
    assert segments[1]["text"] == "Hello world, 92."


def test_sensevoice_words_that_do_not_line_up_fall_back_to_characters() -> None:
    """`words` 的个数和时间对不上时不硬配(那正是错位的来源),退回逐字配 —— Paraformer 的老路。"""
    segments = asr_worker.funasr_sentences_to_segments(
        [{"start": 0, "end": 500, "text": "你好", "timestamp": [[0, 200], [200, 400]], "spk": 0}],
        words=["你好"],
    )
    assert [w["word"] for w in segments[0]["words"]] == ["你", "好"]


def test_paraformer_text_field_still_works() -> None:
    """老字段不能因此失效:同一个函数要同时认两种模型的输出。"""
    segments = asr_worker.funasr_sentences_to_segments([
        {"start": 0, "end": 500, "text": "你好", "timestamp": [[0, 200], [200, 400]], "spk": 1}
    ])
    assert len(segments) == 1
    assert segments[0]["text"] == "你好"
    assert segments[0]["speaker"] == "SPEAKER_01"
