"""MiniMax 海螺(Hailuo)视频生成。

**纯 payload 断言,不打网络**:这个适配器的风险全在"把内部请求翻成 MiniMax 的多模态
content 数组"这一步 —— 官方对 ratio 有条硬规则(图生视频恒为 adaptive、文生视频不能是
adaptive),传错直接被拒,而这类错误在真跑一次之前完全看不出来。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.providers.base import GenerationRequest, ProviderContext, ProviderError
from app.ai.providers.base import FIRST_FRAME, SourceAsset
from app.ai.providers.video.minimax import build_submit_payload, extract_video_url, resolve_model


def _ctx(**kw) -> ProviderContext:
    return ProviderContext(
        profile_id=None,
        vendor="minimax",
        api_key="k",
        base_url=kw.pop("base_url", ""),
        default_model=kw.pop("default_model", ""),
        extra=kw or {},
    )


def test_文生视频给具体比例() -> None:
    payload = build_submit_payload(
        GenerationRequest(kind="video", model="MiniMax-H3", prompt="海边黄昏",
                          parameters={"duration_seconds": 6, "resolution": "2K", "aspect_ratio": "9:16"}),
        _ctx(),
    )
    assert payload["model"] == "MiniMax-H3"
    assert payload["content"] == [{"type": "text", "text": "海边黄昏"}]
    assert payload["duration"] == 6
    assert payload["resolution"] == "2K"
    assert payload["ratio"] == "9:16"


def test_图生视频的比例恒为_adaptive(tmp_path: Path) -> None:
    """官方规定:给了首帧就由首帧决定画面比例,这时传具体比例会被拒。"""
    frame = tmp_path / "f.png"
    frame.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * 32)
    payload = build_submit_payload(
        GenerationRequest(kind="video", model="MiniMax-H3", prompt="走起来",
                          parameters={"aspect_ratio": "16:9"}, sources=tuple(SourceAsset(role=FIRST_FRAME, path=p) for p in (frame,))),
        _ctx(),
    )
    assert payload["ratio"] == "adaptive"
    roles = [item.get("role") for item in payload["content"]]
    assert "first_frame" in roles


def test_时长夹在官方区间内() -> None:
    """4–15 秒。夹住而不是报错 —— 上游给的是 UI 档位,超界时跑最近的合法值比抛 400 有用。"""
    for given, expect in ((1, 4), (6, 6), (99, 15)):
        payload = build_submit_payload(
            GenerationRequest(kind="video", model="", prompt="p", parameters={"duration_seconds": given}), _ctx()
        )
        assert payload["duration"] == expect


def test_没指定模型时回落到_H3() -> None:
    assert resolve_model(GenerationRequest(kind="video", model="", prompt="p"), _ctx()) == "MiniMax-H3"
    assert resolve_model(GenerationRequest(kind="video", model="", prompt="p"), _ctx(default_model="X")) == "X"


def test_终态失败立刻抛而不是等超时() -> None:
    with pytest.raises(ProviderError) as err:
        extract_video_url({"task": {"status": "failed", "error": "content policy"}})
    assert "content policy" in str(err.value)
    # 还在跑 → 返回 None 继续轮询
    assert extract_video_url({"task": {"status": "processing"}}) is None
    assert extract_video_url({"task": {"status": "succeeded", "content": {"url": "https://x/v.mp4"}}}) == "https://x/v.mp4"
