"""报告里加了引号的话,逐条核对是不是取回来的原文;找不到的去掉引号、标为转述。

为什么要这一步(2026-10,评论区洞察真跑 k3,409 / 423 条评论逐条对过):提示词里写了「只引用原文、引号里只放逐字
摘录」之后,报告里仍有加了「」的话在取回的评论里找不到 —— 归纳出来的一句(「都是从COD转过来的兄弟」)、把几条揉成
一句的问题。读的人会以为那是观众的原话。提示词管不住的,在存笔记之前用代码把关。
"""

from __future__ import annotations

import json

from app.domain import quotes
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.executors import get_executor

COMMENTS = [
    {"author": "甲", "text": "看了那么久的三角洲视频，感觉昊天bb那样的主播完全就只能是观赏[Mygo表情包_忧郁]反而老六更适合我们普通玩家", "likes": 86},
    {"author": "乙", "text": "↳ 回复 @甲 :第二个应该是马超的", "likes": 7},
    {"author": "丙", "text": "等哪天游戏大小膨胀到手机装不下就删，现在纯是因为充钱了所以继续玩\n我K60", "likes": 3},
]


def _check(text: str, sources=None) -> quotes.QuoteCheck:
    return quotes.check_quotes({"report": text}, sources if sources is not None else {"comments": COMMENTS})


def test_原文里有的引用照旧留着引号() -> None:
    result = _check("最高赞:「第二个应该是马超的」(👍7)")
    assert result.texts["report"] == "最高赞:「第二个应该是马超的」(👍7)"
    assert (result.checked, result.matched, result.paraphrased) == (1, 1, 0)


def test_找不到的去掉引号_标为转述() -> None:
    result = _check("依据:「都是从COD转过来的兄弟」、“能熟练复述战绩”。")
    assert result.texts["report"] == "依据:都是从COD转过来的兄弟(转述)、能熟练复述战绩(转述)。"
    assert (result.checked, result.matched, result.paraphrased) == (2, 0, 2)
    assert result.unmatched == ["都是从COD转过来的兄弟", "能熟练复述战绩"]


def test_全半角_空白_表情码不算改字() -> None:
    # 模型把全角逗号写成半角、去掉了表情码和换行:字没改,算原文
    result = _check("「看了那么久的三角洲视频,感觉昊天bb那样的主播完全就只能是观赏反而老六更适合我们普通玩家」"
                    "「现在纯是因为充钱了所以继续玩 我K60」")
    assert (result.matched, result.paraphrased) == (2, 0)


def test_用省略号删节的长评论_每一段按顺序都在同一条评论里才算原文() -> None:
    assert _check("「看了那么久的三角洲视频……老六更适合我们普通玩家」").matched == 1
    # 顺序反了不算
    assert _check("「老六更适合我们普通玩家……看了那么久的三角洲视频」").paraphrased == 1
    # 两条评论各取一半拼成一句,不算
    assert _check("「第二个应该是马超的……我K60」").paraphrased == 1


def test_原文可以是_JSON_列表_JSON_文字_或者普通文字() -> None:
    as_text = json.dumps(COMMENTS, ensure_ascii=False)
    for sources in ({"comments": as_text}, {"data": "### 评论区\n- 👍7 ↳ 回复 @甲 :第二个应该是马超的"}, {"x": [{"y": COMMENTS}]}):
        assert _check("「第二个应该是马超的」", sources).matched == 1, sources


def test_几段文字一起核对_各自改写_合起来计数() -> None:
    result = quotes.check_quotes(
        {"verdict": "大家在问「第二个应该是马超的」", "replies": "建议回复:「感谢支持,下期安排」"},
        {"comments": COMMENTS},
    )
    assert result.texts == {"verdict": "大家在问「第二个应该是马超的」", "replies": "建议回复:感谢支持,下期安排(转述)"}
    assert (result.checked, result.matched, result.paraphrased) == (2, 1, 1)


def test_说明这一次核对的结果() -> None:
    assert _check("「第二个应该是马超的」「编的一句话」").summary() == (
        "引用核对:加了引号的 2 处里,1 处在取回的原文里找得到;1 处找不到,已去掉引号、标为转述。"
    )
    assert _check("「第二个应该是马超的」").summary() == "引用核对:加了引号的 1 处都在取回的原文里找得到。"
    assert _check("没有引号的报告").summary() == "引用核对:没有加引号的引用。"


def test_节点_核对引用() -> None:
    spec = NODE_TYPES["quote_check"]
    assert set(spec["outputs"]) == {"texts", "checked", "matched", "paraphrased", "unmatched", "summary"}
    out = get_executor("quote_check")(None, None, {
        "texts": {"report": "「第二个应该是马超的」「编的」"},
        "sources": {"comments": json.dumps(COMMENTS, ensure_ascii=False)},
    })
    assert out["texts"] == {"report": "「第二个应该是马超的」编的(转述)"}
    assert (out["checked"], out["matched"], out["paraphrased"], out["unmatched"]) == (2, 1, 1, ["编的"])
    assert out["summary"].startswith("引用核对:")
