"""本机识别那个小 ViT 的 numpy 前向(app/ai/runtime/nsfw_vit):对着 timm 算的数。

夹具(tests/fixtures/nsfw/)是一份随机小权重的 timm VisionTransformer —— 两层、24 宽、3 个头、4 像素一块、输入 16 —— 和一张
27×19 的图(不是方的、不是块的整数倍,缩放和居中裁都要走到);expected.json 是 timm 1.0.30 用这个模型的 eval 变换(短边双三次
缩放、居中裁、均值 / 方差 0.5)算出的 logits。真模型(Marqo/nsfw-image-detection-384)开工前对过同一套:logits 差在 1e-5 以内。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.ai.runtime import nsfw_vit

FIXTURES = Path(__file__).parent / "fixtures" / "nsfw"


def test_前向和timm算的一样() -> None:
    weights = nsfw_vit.load(FIXTURES / "tiny-vit.safetensors")
    expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
    assert nsfw_vit.input_size(weights) == 16, "输入边长从位置编码和块大小读"
    with Image.open(FIXTURES / "picture.png") as image:
        logits = nsfw_vit.forward(weights, nsfw_vit.prepare(image, 16), heads=expected["heads"])
        probability = nsfw_vit.nsfw_probability(weights, image)
    assert np.allclose(logits, expected["logits"], atol=1e-4), (logits, expected["logits"])
    exp = np.exp(np.array(expected["logits"]) - max(expected["logits"]))
    assert probability == pytest.approx(exp[0] / exp.sum(), abs=1e-4), "第 0 类是 NSFW"


def test_预处理_短边缩放_居中裁_归一到正负一() -> None:
    image = Image.new("RGB", (64, 16), (255, 0, 0))
    image.paste((0, 0, 255), (0, 0, 16, 16))  # 最左边四分之一是蓝的:缩成 32×8 再居中裁 8×8,不在里面
    pixels = nsfw_vit.prepare(image, 8)
    assert pixels.shape == (3, 8, 8) and pixels.dtype == np.float32
    assert pixels[0].min() > 0.9 and pixels[2].max() < -0.9, "裁掉的是两边;红色归一到 +1,没有的蓝到 -1"


def test_读不懂的权重说不行(tmp_path) -> None:
    bad = tmp_path / "bad.safetensors"
    bad.write_bytes(b"\x00\x00")
    with pytest.raises(nsfw_vit.WeightsError):
        nsfw_vit.load(bad)
    header = json.dumps({"head.weight": {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}}).encode()
    bad.write_bytes(struct.pack("<Q", len(header)) + header + b"\x00\x00")
    with pytest.raises(nsfw_vit.WeightsError, match="F32"):
        nsfw_vit.load(bad)
