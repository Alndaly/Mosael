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


def test_张数数的是跑几遍_说明要的批量也进描述符() -> None:
    """ComfyUI 的工作流「张数」是跑几遍(`x-count-unit: runs`),一遍每个结果节点出几张写在 `x-batch`:宿主把它们记成
    `num_images_unit` / `batch_per_run`,表单据此把这一格叫「跑几遍」、写清一遍出几张。别的值、不是正整数的批量不收。"""
    from app.domain.generation.plugin_connections import descriptor
    from app.domain.plugins.generation import _model

    runs = {"type": "integer", "minimum": 1, "maximum": 4, "default": 1, "x-count-unit": "runs", "x-batch": 4}
    caps = descriptor(_model({**TWO_SAVES, "parameters": {"num_images": runs}}, _text))
    assert caps["num_images_unit"] == "runs" and caps["batch_per_run"] == 4 and caps["max_num_images"] == 4
    unknown = descriptor(_model({**TWO_SAVES, "parameters": {"num_images": {**runs, "x-batch": 0}}}, _text))
    assert unknown["num_images_unit"] == "runs" and "batch_per_run" not in unknown, "判不出批量:不报"
    plain = descriptor(_model({**TWO_SAVES, "parameters": {"num_images": {**runs, "x-count-unit": "frames"}}}, _text))
    assert "num_images_unit" not in plain and "batch_per_run" not in plain, "张数就是张数的模型不写"


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


#: 尺寸只是推荐的几档、任意宽高都收(ComfyUI 的工作流按 8 的倍数取整):`examples` 是推荐值,`minimum` 每边下限,
#: `multipleOf` 插件取整到它的倍数。
FREE_SIZE: dict[str, Any] = {
    "id": "girl.json",
    "label": "girl",
    "kind": "image",
    "parameters": {
        "size": {"type": "string", "examples": ["1280x1920", "512x512", "1024x1024"], "default": "1280x1920",
                 "minimum": 16, "multipleOf": 8},
    },
}


def test_尺寸是推荐值时任意宽高都收() -> None:
    """用户拍板:ComfyUI 生成的尺寸放开成任意宽高。此前「工作流自己的尺寸 + 8 档常用尺寸」是硬限制,768x1024 被拒
    (「size 只能是:…」)。插件改成用 `examples` 说推荐值,宿主照旧摆这几档,但手填的也收;格式不对、比下限小的照样拒。"""
    import pytest

    from app.domain.generation.operations import GenerationDomainError, validate_parameters
    from app.domain.generation.plugin_connections import descriptor
    from app.domain.plugins.generation import _model

    caps = descriptor(_model(FREE_SIZE, _text))
    assert caps["sizes"] == ["1280x1920", "512x512", "1024x1024"] and caps["default_size"] == "1280x1920"
    assert caps["custom_size"] == {"minimum": 16, "multiple_of": 8}
    for size in ("768x1024", "1280x1920", "770 x 1021"):
        validate_parameters("plugin:x", "girl.json", "image", {"size": size}, capabilities=caps)
    for size in ("big", "768", "8x8", "0x1024"):
        with pytest.raises(GenerationDomainError):
            validate_parameters("plugin:x", "girl.json", "image", {"size": size}, capabilities=caps)

    strict = descriptor(_model({**FREE_SIZE, "parameters": {"size": {"type": "string", "enum": ["512x512"]}}}, _text))
    assert "custom_size" not in strict, "只给 enum 的照旧是只能从里面挑"
    with pytest.raises(GenerationDomainError):
        validate_parameters("plugin:x", "girl.json", "image", {"size": "768x1024"}, capabilities=strict)
