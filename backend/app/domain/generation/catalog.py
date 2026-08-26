from __future__ import annotations

from typing import Any



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

#: 万相(通义)视频。**尺寸用 `宽*高` 而不是 480p 这种档位名** —— 百炼收的就是像素对
#: (真机:`size=1*1` 会被拒成 `size is not supported`,而 `832*480` 通过)。
#: 这几个档是实测确认过被接受的,不是照文档抄的。
WAN_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video"],
    "endpoint": "dashscope",
    "parameter_keys": ["duration_seconds", "size", "first_frame"],
    "duration_seconds": [5],
    "default_duration_seconds": 5,
    "sizes": ["832*480", "480*832", "1280*720", "720*1280"],
    "default_size": "832*480",
    "max_duration_seconds": 5,
    "supports_audio": False,
}

#: Seedance 2 的时长是**区间,不是两个档位**。此前写的是 `[5, 10]`,于是界面只给这两个
#: 选项 —— 而真机实测 4 到 15 秒的任意整数都收(3 秒和 16 秒各自被拒成
#: `the specified duration is not supported`)。枚举留空,界面自动落到 min/max 数字框。
SEEDANCE_2_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video"],
    "endpoint": "ark",
    "parameter_keys": ["duration_seconds", "resolution", "first_frame", "last_frame", "reference_image"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "720p",
    "min_duration_seconds": 4,
    "max_duration_seconds": 15,
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

#: MiniMax 海螺 H3(2026-07)。原生 2K、4–15 秒、可给首帧;文生视频必须给具体比例,
#: 图生视频恒为 adaptive(见 ai/providers/minimax_video.py)。
MINIMAX_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video"],
    "parameter_keys": [
        "duration_seconds",
        "resolution",
        "aspect_ratio",
        "first_frame",
        "last_frame",
        "reference_image",
    ],
    "duration_seconds": [4, 6, 10, 15],
    "default_duration_seconds": 6,
    "resolutions": ["2K"],
    "default_resolution": "2K",
    "aspect_ratios": ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
    "default_aspect_ratio": "16:9",
    "max_duration_seconds": 15,
    "supports_audio": True,
}

BUILTIN_MODELS = [
    {
        "id": "minimax:MiniMax-H3:video",
        "provider": "minimax",
        "kind": "video",
        "model": "MiniMax-H3",
        "capabilities": MINIMAX_VIDEO_CAPABILITIES,
    },
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
        "id": "bytedance:doubao-seedream-4-0-250828:image",
        "provider": "bytedance",
        "kind": "image",
        "model": "doubao-seedream-4-0-250828",
        "capabilities": SEEDREAM_4_IMAGE_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedream-3-0-t2i-250415:image",
        "provider": "bytedance",
        "kind": "image",
        "model": "doubao-seedream-3-0-t2i-250415",
        "capabilities": SEEDREAM_3_IMAGE_CAPABILITIES,
    },
    {
        # 下面这几个模型 id 都真机验证过存在(2026-08-24)。**它们不在兼容模式的 /models
        # 目录里** —— 那个接口只列 OpenAI 兼容的模型,而视频走百炼原生端点,所以必须在这里
        # 写出来,否则用户在界面上一个也选不到(真机:目录只返回 wan2.7-image 两个图像模型)。
        "id": "alibaba:wan2.2-t2v-plus:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.2-t2v-plus",
        "capabilities": WAN_VIDEO_CAPABILITIES,
    },
    {
        "id": "alibaba:wan2.5-t2v-preview:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.5-t2v-preview",
        "capabilities": WAN_VIDEO_CAPABILITIES,
    },
    {
        "id": "alibaba:wan2.5-i2v-preview:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.5-i2v-preview",
        "capabilities": WAN_VIDEO_CAPABILITIES,
    },
    {
        "id": "alibaba:wan2.6-i2v-flash:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.6-i2v-flash",
        "capabilities": WAN_VIDEO_CAPABILITIES,
    },
    {
        "id": "alibaba:wan2.7-i2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-i2v",
        "capabilities": WAN_VIDEO_CAPABILITIES,
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
            "modes": ["text-to-video", "image-to-video", "keyframes-to-video"],
            "parameter_keys": ["duration_seconds", "aspect_ratio", "first_frame", "last_frame", "negative_prompt"],
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


#: 某个 vendor 在某种生成能力下的**兜底**描述符。目录里没登记的模型(私有部署、别名、
#: 用户手填的)照样要能出现在选择器里并给出一组可用参数 —— 缺描述符不该等于"不能用"。
_FALLBACK_BY_KIND: dict[str, dict[str, Any]] = {
    "image": {
        "modes": ["text-to-image"],
        "parameter_keys": ["size", "negative_prompt"],
        "sizes": ["1024x1024"],
        "default_size": "1024x1024",
        "max_num_images": 1,
    },
    "video": {
        "modes": ["text-to-video"],
        "parameter_keys": ["duration_seconds"],
        "duration_seconds": [5],
        "default_duration_seconds": 5,
        "max_duration_seconds": 10,
    },
}


def capabilities_for(vendor: str, model: str, kind: str) -> dict[str, Any]:
    """某个模型在某种生成能力下的参数描述符(尺寸/时长/支持哪些参数)。

    **这是关于供应商 API 的静态知识,不是用户配置** —— 所以它是一张查表,不再是数据库里的行。
    以前每条描述符都在 `generation_models` 里占一行,于是"有哪些模型可选"这件事有了第二个
    答案:设置页看 provider_models,生成页看 generation_models,两边永远对不齐(ComfyUI 的
    工作流只在后者里,而且是个叫 `workflow` 的假模型 id)。

    精确匹配 (provider, model, kind) 优先;同 vendor 同 kind 的第一条次之(同系模型参数通常
    一致);都没有就用按 kind 的保守兜底。
    """
    return known_capabilities_for(vendor, model, kind) or dict(_FALLBACK_BY_KIND.get(kind, {}))


def known_capabilities_for(vendor: str, model: str, kind: str) -> dict[str, Any] | None:
    """同上,但**查不到就是 None**,不给兜底。

    兜底那份是给界面用的 —— 总得渲染出点什么。校验不能用它:落到兜底的意思是「我们不认识
    这个模型」(用户自建的、ComfyUI 的工作流),拿那份窄名单去拦,会挡住本来能用的参数。
    两种需求共用一个返回值时,分不出「它只支持这些」和「我们不知道它支持什么」。
    """
    for item in BUILTIN_MODELS:
        if item["provider"] == vendor and item["model"] == model and item["kind"] == kind:
            return dict(item["capabilities"])
    for item in BUILTIN_MODELS:
        if item["provider"] == vendor and item["kind"] == kind:
            return dict(item["capabilities"])
    return None


def builtin_models_for(vendor: str, kind: str) -> list[str]:
    """该 vendor 在该能力下的内置模型名 —— 用户没在设置里加过任何模型时的候选。"""
    return [item["model"] for item in BUILTIN_MODELS if item["provider"] == vendor and item["kind"] == kind]


def generation_options(db, kind: str) -> list[dict[str, Any]]:
    """能用来生成的 (连接 × 模型) 列表 —— **唯一**的那份。

    以前这份列表是前端现拼的:拿 generation_models 的目录、enabled 的档案、provider_defaults
    三张表在浏览器里做交叉连接。三份数据任何一份的口径变一点,拼出来的东西就和设置页看到的
    对不上 —— ComfyUI 的工作流只在目录里(还是个叫 `workflow` 的假模型 id)、设置页里加的
    模型进不了生成页,都是这么来的。

    现在只有一条线:**有哪些模型 = provider_models**(设置页管的就是它),参数描述符按
    (vendor, model, kind) 查静态表,适配器可用性问 get_provider。
    """
    from app.ai.providers import get_provider
    from app.domain import provider_models

    options: list[dict[str, Any]] = []
    for model in provider_models.models_for_capability(db, kind):
        profile = model.profile
        if profile is None:
            continue
        vendor = profile.vendor
        options.append(
            {
                "id": f"{profile.id}:{kind}:{model.model_id}",
                "provider_profile_id": profile.id,
                "profile_name": profile.name,
                "provider": vendor,
                "kind": kind,
                "model": model.model_id,
                "label": f"{profile.name} · {model.display_name or model.model_id}",
                "capabilities": capabilities_for(vendor, model.model_id, kind),
                # 适配器不可用的照样列出来但标出来 —— 藏起来的话,用户配好了却找不到,
                # 只会以为是自己配错了。
                "adapter_available": get_provider(vendor, kind) is not None,
            }
        )
    options.sort(key=lambda item: (item["profile_name"], item["model"]))
    return options
