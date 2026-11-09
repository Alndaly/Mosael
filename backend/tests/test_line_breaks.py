"""字幕换行:一整句中文也要断开,不让字冲出画面(「雨夜归灯」成片实测一行超宽)。"""

from __future__ import annotations

from app.media.line_breaks import columns, wrap

NARRATION = "一盏往后退。脚步声不急，也不停，像认得这条空路。积水晃一下，远处的暖黄就亮一下。然后，他停住，收伞，抬头。雨声忽然低了。"


def test_全角两栏_半角一栏() -> None:
    assert columns("雨夜ab，.") == 2 + 2 + 1 + 1 + 2 + 1


def test_放得下就一行_原样() -> None:
    assert wrap("雨声忽然低了。", 40) == ["雨声忽然低了。"]


def test_长句每行都不超宽_字一个不少() -> None:
    lines = wrap(NARRATION, 40)
    assert len(lines) > 1
    #: 挂回上一行的收尾标点最多多出一个全角字。
    assert all(columns(line) <= 40 + 2 for line in lines)
    assert "".join(lines) == NARRATION


def test_优先断在句读之后() -> None:
    lines = wrap(NARRATION, 40)
    assert all(line[-1] in "，。" for line in lines[:-1]), lines


def test_没有标点也在字间断开() -> None:
    lines = wrap("雨" * 50, 40)
    assert [columns(line) for line in lines] == [40, 40, 20]


def test_收尾标点不放在行首() -> None:
    #: 第 21 个字后面紧跟「。」—— 断在 20 个字处,「。」会落到下一行开头,要挂回来。
    lines = wrap("雨" * 20 + "。" + "风" * 5, 40)
    assert lines[0].endswith("。") and not lines[1].startswith("。")


def test_英文按词断() -> None:
    lines = wrap("the rain keeps falling on the empty street tonight", 20)
    assert all(columns(line) <= 20 for line in lines)
    assert " ".join(lines) == "the rain keeps falling on the empty street tonight"


def test_超长的英文词只好硬切() -> None:
    assert wrap("a" * 25, 10) == ["a" * 10, "a" * 10, "a" * 5]


def test_原有换行照留() -> None:
    assert wrap("第一行\n第二行", 40) == ["第一行", "第二行"]
