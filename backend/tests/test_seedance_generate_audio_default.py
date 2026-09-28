"""Seedance 默认出有声视频:方舟文档里 `generate_audio` 默认就是 true。

描述符不声明 `default_generate_audio` 时,画板视频节点和 AI 工作室的「生成音频」开关读成关,
出来的全是静音片 —— 用户得每次手动打开,和直接调接口的结果也不一样。
"""

from __future__ import annotations

from app.domain.generation.catalog import BUILTIN_MODELS


def test_支持有声的_Seedance_默认都开着声音() -> None:
    seedance = [row for row in BUILTIN_MODELS if "seedance" in row["model"].lower()
                and row["capabilities"].get("supports_generate_audio")]
    assert any(row["provider"] == "bytedance" for row in seedance), "方舟直连的 Seedance 要在扫描面里"
    muted = [row["id"] for row in seedance if row["capabilities"].get("default_generate_audio") is not True]
    assert muted == []
