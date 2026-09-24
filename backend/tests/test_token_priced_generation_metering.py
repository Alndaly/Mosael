"""按 token 计价的生成(Seedance 视频、GPT Image 生图):计量要记**回包里实际计费的 token 数**。

官方价目表给这两种模型预填的是「每百万输出 token」的价(见 domain/price_reference)。适配器
只报请求侧那份(按提示词估的几十个 token)的话,规则要么对不上、要么对上一个差好几个数量级的数。
"""

from __future__ import annotations

from app.ai.providers.adapters.bytedance.ark.video import seedance_metering
from app.ai.providers.adapters.openai.image import image_metering
from app.ai.providers.contracts.generation import GenerationRequest
from app.domain.usage import _quantity_for_unit


def test_seedance_records_the_billed_completion_tokens() -> None:
    request = GenerationRequest(kind="video", model="doubao-seedance-2-0-260128", prompt="一只猫", parameters={"duration_seconds": 5})
    units = seedance_metering(request, {"status": "succeeded", "usage": {"completion_tokens": 108_900, "total_tokens": 108_900}})
    assert units["output_tokens"] == 108_900
    assert units["video_seconds"] == 5.0, "请求侧的计量照旧保留"
    assert _quantity_for_unit(units, "million_output_token") == 0.1089


def test_seedance_without_usage_stays_unpriceable() -> None:
    """回包没带 usage 就不编一个 —— 按 token 的规则对不上,账上照实显示未定价。"""
    request = GenerationRequest(kind="video", model="doubao-seedance-2-0-260128", prompt="一只猫")
    units = seedance_metering(request, {"status": "succeeded"})
    assert "output_tokens" not in units
    assert _quantity_for_unit(units, "million_output_token") is None


def test_gpt_image_records_image_output_tokens() -> None:
    request = GenerationRequest(kind="image", model="gpt-image-2", prompt="a cat", parameters={"num_images": 1})
    units = image_metering(request, {"data": [], "usage": {"input_tokens": 12, "output_tokens": 4160, "total_tokens": 4172}})
    assert (units["output_tokens"], units["images"]) == (4160, 1)
    assert image_metering(request, {"data": []}).get("output_tokens") is None
