from __future__ import annotations

from app.core.http_retry import auth_headers
from app.domain.generation.prompt_optimizer import guide_for


def test_empty_api_key_sends_no_auth_header() -> None:
    # 空密钥不能变成 "Bearer "(尾随空格)—— httpx 判定为非法头值直接抛,而报错内容和鉴权
    # 毫无关系。
    #
    # **这条注释自己记着这条规矩搬过几次家**:先只护着提示词优化一处,然后搬进 ai_chat
    # 让所有对话调用一起覆盖 —— 而 `ai/model_catalog` 仍然不知道它存在,于是本地端点的
    # 模型目录整整静默失败了一段时间(设置页选择器永远是空的、本地 qwen3 按 32K 回退窗口
    # 提前四倍压缩)。现在它在 `core/http_retry`,两侧都 import 同一份,并有棘轮盯着不许
    # 出现第三处手写(test_bearer_header_is_built_in_one_place)。
    #
    # 每一次搬家都是"又发现一处",而不是"设计变了" —— 这正是「同一份语义要在多处成立」
    # 那一类问题的样子。
    assert auth_headers("") == {}
    assert auth_headers("sk-abc") == {"Authorization": "Bearer sk-abc"}


def test_sd_platform_wants_tags_and_negative() -> None:
    """SD 那一路的写法由模型自己说(描述符的 `prompt_dialect`),不由 vendor 推 —— 同一个 ComfyUI 上
    也有吃自然语言的 Flux 工作流。"""
    g = guide_for("plugin:dev.mosael.comfyui", "portrait.json", "sd-tags")
    assert g.wants_negative is True
    assert g.prompt_lang == "en"
    assert "标签" in g.style  # tag-style guidance


def test_gpt_image_natural_language_no_negative() -> None:
    g = guide_for("openai", "gpt-image-2")
    assert g.wants_negative is False
    assert g.prompt_lang == "en"


def test_qwen_chinese_friendly_with_negative() -> None:
    g = guide_for("alibaba", "qwen-image")
    assert g.wants_negative is True
    assert g.prompt_lang == "zh-ok"


def test_seedream_chinese_friendly_no_negative() -> None:
    g = guide_for("bytedance", "doubao-seedream-4-0-250828")
    assert g.prompt_lang == "zh-ok"
    assert g.wants_negative is False


def test_edit_model_switches_to_instruction_mode() -> None:
    g = guide_for("alibaba", "qwen-image-edit")
    assert g.is_edit is True
    assert "编辑" in g.label
    assert g.wants_negative is False  # edit instructions don't take a negative


def test_unknown_provider_falls_back_to_generic_natural() -> None:
    g = guide_for("some-new-provider", "whatever")
    assert g.label == "通用"
    assert g.wants_negative is False
