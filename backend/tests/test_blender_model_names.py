"""从 Blender 接回来的模型按场景起名:它们归工作区、道具的 3D 模型下拉里也列着,一排「Blender model」分不出是哪个。"""

from __future__ import annotations

from app.domain.blender.bridge import blender_model_name


def test_接回来的模型叫_场景名_Blender_不叠两遍() -> None:
    assert blender_model_name("老街夜景") == "老街夜景 · Blender"
    assert blender_model_name("老街夜景 · Blender") == "老街夜景 · Blender", "接回成新场景时场景名已经带着后缀"
    assert blender_model_name("  ") == "Blender"
