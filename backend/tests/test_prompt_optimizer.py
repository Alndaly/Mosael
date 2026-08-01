from __future__ import annotations

from app.domain.generation.prompt_optimizer import _auth_headers, guide_for


def test_empty_api_key_sends_no_auth_header() -> None:
    # An empty key must NOT become "Bearer " — httpx rejects that as an illegal header value.
    assert _auth_headers("") == {}
    assert _auth_headers("sk-abc") == {"Authorization": "Bearer sk-abc"}


def test_sd_platform_wants_tags_and_negative() -> None:
    g = guide_for("comfyui", "workflow")
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
