"""下拉的显示名:`{值: 值}` 那种恒等项不写进去 —— 界面本来就读 `option_labels?.[值] ?? 值`。

## 现场

`form.option_labels` 是**整份插件页载荷里最大的一块**:对着真机 8120 量,46 个工具的清单里它 1,216,752
字节(占 41.5%),而其中 98.4% 的项 label 就是 value —— 几百项的 LoRA / 大模型下拉把自己那份文件名又照抄
了一遍(`{"0_11Xx_B.safetensors": "0_11Xx_B.safetensors", …}`,17,269 项里 16,995 项是这种)。587 个带下拉
的字段里 431 个整张表全是恒等项。这一格是 `translated_spec` 无条件给每个选项算出来的,`option_label` 对没有
登记译名的选项回落到值本身,于是给一份「没有信息」的表付了一整份字节。

## 钉的是什么

- 恒等项不写;**翻过的照旧写着**(是 / 否、时间线算子那些登记过 `wfOpt_*` 的);
- 界面那一行字**逐项不变**:五个读它的地方(NodeConfigForm、ItemsField、画板三个 composer)都是
  `option_labels?.[值] ?? 值`,恒等项在不在,取到的都是值本身;
- 值一个都不少:`options` 是整张(ADR 0044 修订否掉过「把长下拉删掉」),这里只去掉照抄自己的那份显示名。
"""

from __future__ import annotations

import json

from app.domain.workflows.node_catalog import option_label, translated_spec

#: 几百项的下拉(和真机上那个 LoRA 文件夹一个形状)。
BIG = [f"style/lora_{index:03d}_v{index % 7}.safetensors" for index in range(349)]


def _old_labels(key: str, options: list, locale: str) -> dict[str, str]:
    """改之前那一份:每个选项都给一个显示名,不管它是不是就是值本身。"""
    return {str(option): option_label(key, str(option), locale) for option in options}


def _bytes(node: object) -> int:
    return len(json.dumps(node, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_恒等的显示名不写进去() -> None:
    """没有登记译名的选项(模型文件名那种)不再照抄一份自己。"""
    spec = translated_spec("lora_name_1", {"type": "string", "options": list(BIG)}, "zh")
    assert spec["options"] == BIG, "下拉本身一个值都不能少"
    assert spec["option_labels"] == {}
    assert "option_labels" in spec, "这一格还在(空表 = 这一格没有要另写的显示名),键的名字和顺序不变"
    #: 值越多的表省得越多:349 项那一份 33,551 → 11,216 字节(下拉本身占着那 11KB)。
    assert _bytes(spec) < _bytes({"type": "string", "options": list(BIG),
                                  "option_labels": _old_labels("lora_name_1", BIG, "zh")}) * 0.4


def test_翻过的显示名照旧写着() -> None:
    """登记过 `wfOpt_*` 的照旧发(是 / 否、HTTP 方法那种原样显示的也在)。"""
    assert translated_spec("include_previews", {"options": ["true", "false"]}, "zh")["option_labels"] == {
        "true": "是", "false": "否"}
    assert translated_spec("method", {"options": ["GET", "POST"]}, "zh")["option_labels"] == {}


def test_界面那一行字逐项相同() -> None:
    """界面读的是 `option_labels?.[值] ?? 值` —— 新旧两种写法必须给出同一个显示名,逐项。"""
    locales = ("zh", "en")
    for key, spec in (("lora_name_1", {"options": list(BIG)}),
                      ("include_previews", {"options": ["true", "false"]}),
                      ("sampler_name", {"options": ["euler", "dpmpp_2m"]}),
                      ("scheduler", {"options": ["normal", "karras"]}),
                      ("method", {"options": ["GET", "POST"]})):
        for locale in locales:
            new = translated_spec(key, dict(spec), locale)
            old = _old_labels(key, spec["options"], locale)
            for option in spec["options"]:
                assert (new["option_labels"].get(option) or option) == old[option], f"{key}/{option}/{locale}"


def test_一张表里两种项混着也行() -> None:
    """同一格里既有恒等项又有译名时,只留下译名那几项。"""
    spec = translated_spec("type", {"options": ["default", "cpu", "true", "false"]}, "zh")
    assert spec["option_labels"] == {"true": "是", "false": "否"}
    assert spec["options"] == ["default", "cpu", "true", "false"]
