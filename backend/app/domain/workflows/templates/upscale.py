"""长片、数字人共用的「超分到 2K / 4K」那一步。

视频模型直出的清晰度有限(H3 两遍采样到 1728×960),要 2K / 4K 只能另做一步超分。超分不放进生成那张工作流里:
整段 2K 画面一次放进内存要 11 GB,4K 要 24 GB,ComfyUI 那台机器撑不住。所以是**每段单独一次**超分(ComfyUI 那张
图自己分批,见 ComfyUI-Mosael-Plugins 的 `seedvr2_upscale_batched`),模板里在每段上时间线之前多一个节点。

- **认得出的超分工作流**:收一段源视频、有 `6.width` / `6.height` 两项(节点 6 是定尺寸的 ImageScale)。没有这样的
  工作流时模板不加这一步,时间线照旧 1080p;
- **清晰度**是开始参数 `output_resolution`(1080p / 1440p / 2160p):时间线画布和每段超分的目标尺寸都按它和画幅查同一张表,
  所以导出就是这个尺寸。1080p 也走超分:同样的尺寸,细节比模型直出的多。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.domain.workflows.templates.model_choice import FRAME_ASPECTS, ModelChoice, _parameter_keys, _pick

#: 超分工作流定尺寸的那两项。
UPSCALE_WIDTH = "6.width"
UPSCALE_HEIGHT = "6.height"
#: 成片清晰度的几档,按短边。
OUTPUT_RESOLUTIONS: dict[str, int] = {"1080p": 1080, "1440p": 1440, "2160p": 2160}
DEFAULT_OUTPUT_RESOLUTION = "1440p"


def resolution_options() -> list[dict[str, str]]:
    """开始参数 `output_resolution` 的下拉选项。"""
    labels = {"1080p": "1080p", "1440p": "2K · 1440p", "2160p": "4K · 2160p"}
    return [{"value": name, "label": labels[name]} for name in OUTPUT_RESOLUTIONS]


def frame_table() -> dict[str, dict[str, dict[str, int]]]:
    """画幅 → 清晰度 → 画布宽高。按 1080p 那一档等比放大,宽高取偶数(编码器要)。"""
    table: dict[str, dict[str, dict[str, int]]] = {}
    for aspect, (width, height) in FRAME_ASPECTS.items():
        base = min(width, height)
        table[aspect] = {
            name: {"width": round(width * short / base / 2) * 2, "height": round(height * short / base / 2) * 2}
            for name, short in OUTPUT_RESOLUTIONS.items()
        }
    return table


def upscale_model(db: Session, user_id: str) -> ModelChoice:
    """配好的超分工作流;没有就留空,模板不加超分那一步。"""
    return _pick(db, user_id, "video", lambda db_, choice: {UPSCALE_WIDTH, UPSCALE_HEIGHT} <= set(_parameter_keys(db_, choice)))


def frame_plan_node(position: dict[str, int]) -> dict[str, Any]:
    """按开始参数的画幅和清晰度查画布宽高:时间线和每段超分读的是这同一个值。"""
    return {
        "id": "frame_plan", "type": "json_extract",
        "name": {"zh": "按画幅和清晰度取尺寸", "en": "Pick the size for the aspect ratio and resolution"},
        "position": position,
        "config": {"source": json.dumps(frame_table(), ensure_ascii=False),
                   "path": "{{start.aspect_ratio}}.{{start.output_resolution}}"},
    }


def upscale_node(node_id: str, model: ModelChoice, *, asset: str, width: str, height: str,
                 position: dict[str, int]) -> dict[str, Any]:
    """把 `asset` 这段视频超分到 `width` × `height`。"""
    return {
        "id": node_id, "type": "ai_generate",
        "name": {"zh": "超分到成片清晰度", "en": "Upscale to the output resolution"},
        "position": position,
        "config": {
            "provider": model.provider, "provider_profile_id": model.profile_id, "model": model.model, "kind": "video",
            "prompt": "",
            "parameters": {UPSCALE_WIDTH: width, UPSCALE_HEIGHT: height},
            "source_assets": [f"{asset}:source_video"],
        },
    }


__all__ = [
    "DEFAULT_OUTPUT_RESOLUTION",
    "OUTPUT_RESOLUTIONS",
    "UPSCALE_HEIGHT",
    "UPSCALE_WIDTH",
    "frame_plan_node",
    "frame_table",
    "resolution_options",
    "upscale_model",
    "upscale_node",
]
