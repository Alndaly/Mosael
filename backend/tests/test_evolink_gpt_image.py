"""Evolink 上的 GPT Image:gpt-image-2、gpt-image-2-beta、gpt-image-2.5-flare / sunburst,以及 gpt-image-1.5。

用户要把生图从 147ai 换到 Evolink。依据 Evolink 的文档页(2026-10-04 查证):
- evolink.ai/docs/en/api-manual/image-series/gpt-image-2/gpt-image-2-image-generation
- evolink.ai/docs/en/api-manual/image-series/gpt-image-2/gpt-image-2-beta-image-generation
- evolink.ai/docs/en/api-manual/image-series/gpt-image-2.5/gpt-image-2.5-image-generation
- evolink.ai/docs/en/api-manual/image-series/gpt-image-1.5/gpt-image-1.5-image-generation

**画质(quality)和分辨率档(resolution)决定价钱**:gpt-image-2 按 token 计费,1K 1:1 低画质约 $0.0053 一张,
2K 高画质约 $0.386 —— 差七十多倍。此前适配器只发 size / n / image_urls,画质落在服务商的默认值上
(gpt-image-2 默认 medium、gpt-image-1.5 默认 high),控费等于失灵。所以画质和分辨率档成了表单里能选的参数,
默认用最便宜的 low + 1K,由用户往上调。
"""

from __future__ import annotations

import pytest

from app.ai.providers.adapters.evolink.generation import build_image_payload
from app.ai.providers.contracts.generation import GenerationRequest
from app.domain.generation.catalog import known_capabilities_for
from app.domain.generation.operations import GenerationDomainError, validate_parameters

RATIOS = ["1:1", "1:2", "2:1", "1:3", "3:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9"]


def _caps(model: str) -> dict:
    caps = known_capabilities_for("evolink", model, "image")
    assert caps is not None, f"{model} 不在 Evolink 的内置目录里"
    return caps


@pytest.mark.parametrize("model", ["gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"])
def test_token_priced_gpt_images_choose_quality_and_resolution_and_default_to_the_cheapest(model: str) -> None:
    caps = _caps(model)
    assert {"quality", "resolution", "size", "num_images", "reference_image"} <= set(caps["parameter_keys"])
    assert caps["default_quality"] == "low", "默认最便宜的那档,由用户往上调"
    assert caps["resolutions"] == ["1K", "2K", "4K"] and caps["default_resolution"] == "1K"
    assert caps["default_size"] == "1:1", "按画幅比出图,分辨率档才生效(auto 会忽略它)"
    assert set(RATIOS) <= set(caps["sizes"]) and "auto" in caps["sizes"]
    assert caps["source_limits"] == {"reference_image": 16}
    assert caps["max_num_images"] == 10
    assert caps["max_prompt_chars"] == 32000


def test_quality_tiers_follow_each_model_family() -> None:
    assert _caps("gpt-image-2")["parameter_choices"]["quality"] == ["low", "medium", "high"]
    for model in ("gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
        assert _caps(model)["parameter_choices"]["quality"] == ["low", "medium", "high", "xhigh", "max"]
    validate_parameters("evolink", "gpt-image-2.5-flare", "image", {"quality": "xhigh"}, capabilities=_caps("gpt-image-2.5-flare"))
    with pytest.raises(GenerationDomainError):
        validate_parameters("evolink", "gpt-image-2", "image", {"quality": "xhigh"}, capabilities=_caps("gpt-image-2"))


def test_the_beta_channel_is_a_fixed_price_1k_single_image_route() -> None:
    """gpt-image-2-beta:固定 $0.015 一张、只出 1K、一次一张,不开放画质,提示词最多 2000 字。"""
    caps = _caps("gpt-image-2-beta")
    assert "quality" not in caps["parameter_keys"] and "resolution" not in caps["parameter_keys"]
    assert caps["max_num_images"] == 1
    assert caps["max_prompt_chars"] == 2000
    assert caps["source_limits"] == {"reference_image": 16}


def test_gpt_image_15_gets_a_quality_choice_too() -> None:
    """Evolink 上的 gpt-image-1.5 默认 high(最贵那档);接上画质参数,默认 low。一次只出一张。"""
    caps = _caps("gpt-image-1.5")
    assert caps["parameter_choices"]["quality"] == ["low", "medium", "high"]
    assert caps["default_quality"] == "low"
    assert caps["max_num_images"] == 1
    assert caps["source_limits"] == {"reference_image": 16}


def test_the_adapter_sends_quality_and_resolution_when_given() -> None:
    request = GenerationRequest(kind="image", model="gpt-image-2", prompt="a cat", parameters={
        "size": "1:1", "num_images": 1, "quality": "low", "resolution": "1K", "background": "opaque", "output_format": "png",
    })
    assert build_image_payload(request, []) == {
        "model": "gpt-image-2", "prompt": "a cat", "size": "1:1", "n": 1,
        "quality": "low", "resolution": "1K", "background": "opaque", "output_format": "png",
    }


def test_the_adapter_sends_nothing_it_was_not_given() -> None:
    """没设的不发(ADR 0015):其余模型的请求一个字节都不变。"""
    request = GenerationRequest(kind="image", model="z-image-turbo", prompt="a cat", parameters={"size": "1:1"})
    assert build_image_payload(request, []) == {"model": "z-image-turbo", "prompt": "a cat", "size": "1:1"}
