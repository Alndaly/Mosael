from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import GenerationModel


OPENAI_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "num_images", "reference_image"],
    "sizes": ["1024x1024", "1536x1024", "1024x1536"],
    "default_size": "1024x1024",
    "max_num_images": 4,
}

QWEN_TEXT_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "num_images", "seed", "negative_prompt"],
    "sizes": ["1024x576", "1024x1024", "576x1024", "768x768", "1280x720"],
    "default_size": "1024x576",
    "max_num_images": 4,
}

QWEN_PRO_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "num_images", "seed", "negative_prompt", "reference_image"],
    "sizes": ["1024x1024", "1536x1024", "1024x1536", "1280x720", "720x1280"],
    "default_size": "1024x1024",
    "max_num_images": 4,
}

QWEN_EDIT_IMAGE_CAPABILITIES = {
    "modes": ["image-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["reference_image"],
    "default_size": "",
    "max_num_images": 1,
}

SEEDREAM_4_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "endpoint": "ark",
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "reference_image"],
    # 4.x 约束:总像素落在 [1280x720, 4096x4096] 区间,故不提供 1024 档。
    "sizes": ["2048x2048", "2304x1728", "1728x2304", "2560x1440", "1440x2560"],
    "default_size": "2048x2048",
    "max_num_images": 1,
}

SEEDREAM_3_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image"],
    "endpoint": "ark",
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "seed"],
    "sizes": ["1024x1024", "864x1152", "1152x864", "1280x720", "720x1280", "1248x832", "832x1248"],
    "default_size": "1024x1024",
    "max_num_images": 1,
}

SEEDANCE_2_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video"],
    "endpoint": "ark",
    "parameter_keys": ["duration_seconds", "resolution", "first_frame"],
    "duration_seconds": [5, 10],
    "default_duration_seconds": 5,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "720p",
    "max_duration_seconds": 10,
    "supports_audio": True,
}

SEEDANCE_1_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video"],
    "endpoint": "las",
    "parameter_keys": ["duration_seconds", "aspect_ratio", "first_frame"],
    "duration_seconds": [5, 10],
    "default_duration_seconds": 5,
    "aspect_ratios": ["16:9", "9:16", "1:1"],
    "default_aspect_ratio": "16:9",
    "max_duration_seconds": 10,
    "supports_audio": False,
}


COMFYUI_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "seed", "steps", "negative_prompt"],
    # 本地生成没有服务端尺寸白名单;这里是常用档,模板可自带任意尺寸。
    "sizes": ["1024x1024", "832x1216", "1216x832", "1280x720", "720x1280"],
    "default_size": "1024x1024",
    "max_num_images": 1,
}

COMFYUI_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video"],
    "max_prompt_chars": 8000,
    # 尺寸/步数/采样器等由所选工作流的动态参数表单调,主控件只留时长/负向(之前 size 有 key 却没
    # sizes、给了 resolutions 又没挂,尺寸下拉是空的——一并去掉)。
    "parameter_keys": ["duration_seconds", "seed", "negative_prompt"],
    "duration_seconds": [3, 5, 10],
    "default_duration_seconds": 5,
    "max_duration_seconds": 10,
    # 视频没有内置图:选一个 ComfyUI 里保存的视频工作流,或在档案里粘贴 API 模板。
    "requires_workflow_template": True,
}

BUILTIN_MODELS = [
    {
        "id": "comfyui:workflow:image",
        "provider": "comfyui",
        "kind": "image",
        "model": "workflow",
        "capabilities": COMFYUI_IMAGE_CAPABILITIES,
    },
    {
        "id": "comfyui:workflow:video",
        "provider": "comfyui",
        "kind": "video",
        "model": "workflow",
        "capabilities": COMFYUI_VIDEO_CAPABILITIES,
    },
    {
        "id": "openai:gpt-image-2:image",
        "provider": "openai",
        "kind": "image",
        "model": "gpt-image-2",
        "capabilities": OPENAI_IMAGE_CAPABILITIES,
    },
    {
        "id": "openai-compatible:gpt-image-2:image",
        "provider": "openai-compatible",
        "kind": "image",
        "model": "gpt-image-2",
        "capabilities": OPENAI_IMAGE_CAPABILITIES,
    },
    {
        "id": "alibaba:qwen-image-2.0-pro:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image-2.0-pro",
        "capabilities": QWEN_PRO_IMAGE_CAPABILITIES,
    },
    {
        "id": "alibaba:qwen-image-edit:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image-edit",
        "capabilities": QWEN_EDIT_IMAGE_CAPABILITIES,
    },
    {
        "id": "alibaba:qwen-image:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image",
        "capabilities": QWEN_TEXT_IMAGE_CAPABILITIES,
    },
    {
        "id": "bytedance-image:doubao-seedream-4-0-250828:image",
        "provider": "bytedance-image",
        "kind": "image",
        "model": "doubao-seedream-4-0-250828",
        "capabilities": SEEDREAM_4_IMAGE_CAPABILITIES,
    },
    {
        "id": "bytedance-image:doubao-seedream-3-0-t2i-250415:image",
        "provider": "bytedance-image",
        "kind": "image",
        "model": "doubao-seedream-3-0-t2i-250415",
        "capabilities": SEEDREAM_3_IMAGE_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-2-0-260128:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-260128",
        "capabilities": SEEDANCE_2_VIDEO_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-2-0-fast-260128:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-fast-260128",
        "capabilities": SEEDANCE_2_VIDEO_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-2-0-mini-260615:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-mini-260615",
        "capabilities": SEEDANCE_2_VIDEO_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-1-5-pro-251215:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-5-pro-251215",
        "capabilities": {**SEEDANCE_1_VIDEO_CAPABILITIES, "supports_audio": True},
    },
    {
        "id": "bytedance:doubao-seedance-1-0-pro-250528:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-0-pro-250528",
        "capabilities": SEEDANCE_1_VIDEO_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-1-0-pro-fast-251015:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-0-pro-fast-251015",
        "capabilities": SEEDANCE_1_VIDEO_CAPABILITIES,
    },
    {
        "id": "google:veo:video",
        "provider": "google",
        "kind": "video",
        "model": "veo",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "first_frame"],
            "duration_seconds": [4, 6, 8],
            "default_duration_seconds": 8,
            "resolutions": ["720p", "1080p"],
            "default_resolution": "1080p",
            "aspect_ratios": ["16:9", "9:16"],
            "default_aspect_ratio": "16:9",
            "max_duration_seconds": 8,
        },
    },
    {
        "id": "kuaishou:kling:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "parameter_keys": ["duration_seconds", "aspect_ratio", "first_frame", "negative_prompt"],
            "duration_seconds": [5, 10],
            "default_duration_seconds": 5,
            "aspect_ratios": ["16:9", "9:16", "1:1"],
            "default_aspect_ratio": "16:9",
            "max_duration_seconds": 10,
        },
    },
]

REMOVED_BUILTIN_MODEL_IDS = {
    "bytedance:seedance:video",
    # seedream 图像改挂独立厂商 bytedance-image(独立档案,互不牵连)
    "bytedance:doubao-seedream-4-0-250828:image",
    "bytedance:doubao-seedream-3-0-t2i-250415:image",
}


def ensure_builtin_generation_models(db: Session) -> None:
    db.execute(delete(GenerationModel).where(GenerationModel.id.in_(REMOVED_BUILTIN_MODEL_IDS)))
    for item in BUILTIN_MODELS:
        existing = db.get(GenerationModel, item["id"])
        if existing is None:
            db.add(GenerationModel(**item))
            continue
        existing.provider = item["provider"]
        existing.kind = item["kind"]
        existing.model = item["model"]
        existing.capabilities = item["capabilities"]
        existing.enabled = True
    db.commit()
