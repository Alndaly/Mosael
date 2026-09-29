"""图像生成的能力描述符(OpenAI 兼容、通义千问、Seedream、Evolink 图像)。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

#: OpenAI 兼容的图像接口(gpt-image-2 等)。真机核过(2026-08-27,经 147ai):
#: **约束是「宽高都能被 16 整除」+ 一个像素数下限**,不是三个固定档 —— 接口原话
#: `Width and height must both be divisible by 16.` 与
#: `Requested resolution is below the current minimum pixel budget.`
#:
#: 二分出的下限落在 589824(768x768,被拒)和 802816(896x896,通过)之间。
#: 1280x720(921600)和 1920x1088 都实测通过,而它们此前一个都不在表里 ——
#: **1280x720 是最常用的横屏尺寸**。
OPENAI_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": [
        "size", "num_images", "reference_image",
        "quality", "background", "output_format", "moderation",
    ],
    "parameter_choices": {
        "quality": ["auto", "low", "medium", "high"],
        "background": ["auto", "transparent", "opaque"],
        "output_format": ["png", "webp", "jpeg"],
        "moderation": ["auto", "low"],
    },
    "default_quality": "auto",
    "default_background": "auto",
    "default_output_format": "png",
    "default_moderation": "auto",
    # **这一条没探出来**:走的是 147ai 这类转售网关,它对张数一律放行,官方端点又没有密钥可打。
    # 16 来自 OpenAI 文档(`/images/edits` 的 `image[]` 上限),适配器此前也是硬编码的 16 —— 
    # 只是把那个数字从代码里挪进描述符,别把它当成和上面几家同等确信的东西。
    "source_limits": {"reference_image": 16},
    "sizes": ["1024x1024", "1536x1024", "1024x1536", "1280x720", "720x1280", "1920x1088"],
    "default_size": "1024x1024",
    "size_multiple_of": 16,
    "max_num_images": 4,
}

QWEN_TEXT_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "num_images", "seed", "negative_prompt", "prompt_extend"],
    "boolean_parameters": ["prompt_extend"],
    "default_prompt_extend": True,
    "sizes": ["1024x576", "1024x1024", "576x1024", "768x768", "1280x720"],
    "default_size": "1024x576",
    "max_num_images": 4,
}

#: 真机核过(2026-08-27)。接口原话把两种模式一起说清楚了:
#: `Model 'qwen-image-2.0-2in1' supports 0~3 image content items.
#:  (0 images = T2I mode, 1~3 images = I2I mode)`
#: 所以它和 qwen-image-edit 不一样:**不给图也能跑**,那就是文生图。
QWEN_PRO_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "num_images", "seed", "negative_prompt", "prompt_extend", "reference_image"],
    "boolean_parameters": ["prompt_extend"],
    "default_prompt_extend": True,
    "source_limits": {"reference_image": 3},
    "sizes": ["1024x1024", "1536x1024", "1024x1536", "1280x720", "720x1280"],
    "default_size": "1024x1024",
    "max_num_images": 4,
}

#: 真机核过(2026-08-27)。接口原话:
#: `For image editing, the message must contain 1~3 image content items.`
#: **下限是 1** —— 零张也被拒(它是编辑模型,没有图就无从编辑),所以进 requires_source。
QWEN_EDIT_IMAGE_CAPABILITIES = {
    "modes": ["image-to-image"],
    "max_prompt_chars": 8000,
    "parameter_keys": ["reference_image"],
    "source_limits": {"reference_image": 3},
    "requires_source": [["reference_image"]],
    "default_size": "",
    "max_num_images": 1,
}

#: 参考图上限 2026-08-27 真机核过,接口原话:
#: `number of reference images cannot exceed 14`。适配器此前只发第一张(走的是单数的
#: source_for),所以挂几张都一样 —— 不报错,只是效果不对。
SEEDREAM_4_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "endpoint": "ark",
    "max_prompt_chars": 8000,
    "parameter_keys": ["size", "reference_image"],
    "source_limits": {"reference_image": 14},
    # 4.x 的约束是**总像素数**,不是固定档:接口原话
    # `image size must be at least 921600 pixels`(= 1280x720)。真机核过(2026-08-27):
    # 1280x720 / 960x960 / 1024x1024 / 4096x4096 全部通过。
    #
    # 原注释写着"故不提供 1024 档"—— 那个推断是错的:1024x1024 是 1048576 像素,高于下限。
    # 档位表是**给下拉用的常用值**,不是限制;要别的尺寸可以手填。
    "sizes": [
        "2048x2048",
        "2304x1728",
        "1728x2304",
        "2560x1440",
        "1440x2560",
        "1280x720",
        "720x1280",
        "1024x1024",
    ],
    "default_size": "2048x2048",
    "min_size_pixels": 921600,
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

EVOLINK_IMAGE_SIZES = [
    "1024x1024", "1024x1536", "1536x1024",
    "1:1", "16:9", "9:16", "2:3", "3:2", "4:3", "3:4", "4:5", "5:4", "21:9",
]

EVOLINK_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image"],
    "max_prompt_chars": 2000,
    "parameter_keys": ["size", "num_images"],
    "sizes": EVOLINK_IMAGE_SIZES,
    "default_size": "1024x1024",
    "max_num_images": 4,
}

EVOLINK_IMAGE_EDIT_CAPABILITIES = {
    **EVOLINK_IMAGE_CAPABILITIES,
    "modes": ["text-to-image", "image-to-image"],
    "parameter_keys": ["size", "num_images", "reference_image"],
    "source_limits": {"reference_image": 14},
}
