"""视频的计量不替请求猜:没说分辨率就不记分辨率;「参考图几张」只数图。

真跑改口型(videoretalk):请求里没有分辨率(成片跟着原视频,交回的是 640×640),账上却写着 resolution 720p;
原视频和驱动音频两份素材被记成 source_images 2。按分辨率分档的价目对着一个猜出来的 720p 就会算错档。
"""

from __future__ import annotations

from pathlib import Path

from app.ai.providers.contracts.generation import (
    DRIVING_AUDIO,
    FIRST_FRAME,
    SOURCE_VIDEO,
    GenerationRequest,
    SourceAsset,
    metering_from_request,
)
from app.domain.generation.runner import _with_request_facts


def _request(model: str, roles: tuple[str, ...], parameters: dict | None = None) -> GenerationRequest:
    return GenerationRequest(kind="video", model=model, prompt="", parameters=parameters or {},
                             sources=tuple(SourceAsset(role=role, path=Path(f"/tmp/{role}")) for role in roles))


def test_改口型没说分辨率_不记分辨率_原视频和音频不算参考图() -> None:
    request = _request("videoretalk", (SOURCE_VIDEO, DRIVING_AUDIO))
    units = metering_from_request(request)
    assert "resolution" not in units, units
    assert units["source_images"] == 0
    facts = _with_request_facts({}, request, None, 6.188)
    assert "resolution" not in facts and facts["source_images"] == 0, facts
    assert facts["video_seconds"] == 6.188, "成片多长照实记"


def test_说了分辨率照记_首帧算一张图() -> None:
    request = _request("wan2.2-s2v", (FIRST_FRAME, DRIVING_AUDIO), {"resolution": "480P"})
    units = metering_from_request(request)
    assert (units["resolution"], units["source_images"]) == ("480P", 1)
    facts = _with_request_facts({}, request, None, 5.562)
    assert (facts["resolution"], facts["source_images"]) == ("480P", 1)
