"""插件模型说**一次交回几份**,以及「结果取自」这类选项的名字(见 docs/PLUGIN_MANIFEST「替宿主做生成」)。

ComfyUI 的一张工作流常常不止一个保存节点(原图 + 放大、几个预览):一次运行交回的是这几个节点各一份(× 张数)。
插件在模型描述里照实说(`outputs_per_run`),给一项「结果取自」(选项名是节点标题 `x-enum-labels`、每个选项一次
交回几份 `x-outputs-per-run`),宿主据此一次摆好那么多格占位。这里钉宿主收这几样的规矩:认得的留下、对不上可选值的
丢掉,给人看的字按看的人的语言挑。
"""

from __future__ import annotations

from typing import Any

from app.core.i18n import get_current_locale, pick_text, set_current_locale


def _text(value: Any) -> str:
    return pick_text(value, "zh") if isinstance(value, dict) else str(value or "")


TWO_SAVES: dict[str, Any] = {
    "id": "two.json",
    "label": "two",
    "kind": "image",
    "outputs_per_run": 2,
    "max_outputs": 8,
    "parameters": {
        "num_images": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
        "output_node": {
            "type": "string",
            "title": {"zh": "结果取自", "en": "Results from"},
            "enum": ["all", "9", "12"],
            "default": "all",
            #: 不在可选值里的(99)、不是字的丢掉。
            "x-enum-labels": {"all": {"zh": "全部(2 个保存节点)", "en": "All (2 save nodes)"}, "9": "原图",
                              "12": "高清", "99": "早删掉的节点", "bad": 3},
            #: 不在可选值里的、不是正整数的丢掉。
            "x-outputs-per-run": {"all": 2, "9": 1, "12": 1, "99": 1, "bad": 0},
        },
    },
}


def test_一次交回几份和选项名字进描述符() -> None:
    from app.domain.generation.plugin_connections import descriptor
    from app.domain.plugins.generation import _model

    model = _model(TWO_SAVES, _text)
    assert model is not None and model.outputs_per_run == 2
    caps = descriptor(model)
    assert caps["outputs_per_run"] == 2
    spec = caps["parameter_schema"]["output_node"]
    assert spec["x-enum-labels"] == {"all": {"zh": "全部(2 个保存节点)", "en": "All (2 save nodes)"}, "9": "原图", "12": "高清"}
    assert spec["x-outputs-per-run"] == {"all": 2, "9": 1, "12": 1}
    assert caps["max_num_images"] == 4

    #: 一次一份(或没说)就不写这一格 —— 描述符不伪造值(ADR 0015)。
    single = _model({**TWO_SAVES, "outputs_per_run": 1}, _text)
    assert "outputs_per_run" not in descriptor(single)
    assert _model({**TWO_SAVES, "outputs_per_run": True}, _text).outputs_per_run == 1
    assert _model({**TWO_SAVES, "outputs_per_run": 999}, _text).outputs_per_run == 64, "有上限"


def test_选项名字按看的人的语言挑() -> None:
    from app.domain.generation.plugin_connections import descriptor
    from app.domain.generation.resolution import _for_reader
    from app.domain.plugins.generation import _model

    caps = descriptor(_model(TWO_SAVES, _text))
    before = get_current_locale()
    set_current_locale("en")
    try:
        readable = _for_reader(caps)["parameter_schema"]["output_node"]
    finally:
        set_current_locale(before)
    assert readable["title"] == "Results from"
    assert readable["x-enum-labels"] == {"all": "All (2 save nodes)", "9": "原图", "12": "高清"}
    assert readable["x-outputs-per-run"] == {"all": 2, "9": 1, "12": 1}
