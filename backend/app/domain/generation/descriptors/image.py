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

# ---- Evolink 上的 GPT Image(2026-10-04 按 Evolink 文档页核对,路径见各条)----
#
# **画质(quality)和分辨率档(resolution)决定价钱。**gpt-image-2 / 2.5 按 token 计费:1K 1:1 低画质约 $0.0053
# 一张,中画质约 $0.012,2K 高画质约 $0.386。不发画质就落在服务商的默认值上(gpt-image-2 / 2.5 默认 medium、
# gpt-image-1.5 默认 high),所以这两项是表单里能选的参数,**默认最便宜的 low + 1K**,由用户往上调。
# 分辨率档只在「按画幅比」出图时生效(size 为 auto 或显式像素时服务商忽略它)—— 默认尺寸因此是 1:1,不是 auto。
# 蒙版(mask_url)文档里有,但这几家的描述符和 OpenAI 那份一样不开放蒙版这个角色,适配器也不传。

#: 15 种画幅比(三份文档同一张表)。
_GPT_IMAGE_RATIOS = ["1:1", "1:2", "2:1", "1:3", "3:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9"]

#: gpt-image-2(evolink.ai/docs/en/api-manual/image-series/gpt-image-2/gpt-image-2-image-generation):
#: 提示词 32000 字;参考图 1–16 张;size = auto / 15 种画幅比 / 显式 WxH(16 的倍数,每边 16–3840,像素 655,360–8,294,400);
#: resolution 1K / 2K / 4K(默认 1K,只对画幅比生效);quality low / medium / high(默认 medium);
#: background opaque / transparent;output_format png / jpeg / webp;n 1–10。
EVOLINK_GPT_IMAGE_2_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 32000,
    "parameter_keys": [
        "size", "resolution", "num_images", "reference_image", "quality", "background", "output_format",
    ],
    "parameter_choices": {
        "quality": ["low", "medium", "high"],
        "background": ["opaque", "transparent"],
        "output_format": ["png", "jpeg", "webp"],
    },
    "default_quality": "low",
    "default_background": "opaque",
    "default_output_format": "png",
    "resolutions": ["1K", "2K", "4K"],
    "default_resolution": "1K",
    "sizes": ["auto", *_GPT_IMAGE_RATIOS, "1024x1024", "1536x1024", "1024x1536"],
    "default_size": "1:1",
    "size_multiple_of": 16,
    "source_limits": {"reference_image": 16},
    "max_num_images": 10,
}

#: gpt-image-2.5-flare(日常出图)/ gpt-image-2.5-sunburst(精修),两个模型同一套参数
#: (evolink.ai/docs/en/api-manual/image-series/gpt-image-2.5/gpt-image-2.5-image-generation):
#: 和 gpt-image-2 一样,只是画质多两档 xhigh / max(默认仍是 medium)。
EVOLINK_GPT_IMAGE_25_CAPABILITIES = {
    **EVOLINK_GPT_IMAGE_2_CAPABILITIES,
    "parameter_choices": {
        **EVOLINK_GPT_IMAGE_2_CAPABILITIES["parameter_choices"],
        "quality": ["low", "medium", "high", "xhigh", "max"],
    },
}

#: gpt-image-2-beta(evolink.ai/docs/en/api-manual/image-series/gpt-image-2/gpt-image-2-beta-image-generation):
#: 固定价一张、只出 1K、n 固定为 1、不开放画质;提示词 2000 字;size = auto / 15 种画幅比;参考图最多 16 张(含在价里)。
EVOLINK_GPT_IMAGE_2_BETA_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 2000,
    "parameter_keys": ["size", "reference_image"],
    "sizes": ["auto", *_GPT_IMAGE_RATIOS],
    "default_size": "1:1",
    "source_limits": {"reference_image": 16},
    "max_num_images": 1,
}

#: gpt-image-1.5(evolink.ai/docs/en/api-manual/image-series/gpt-image-1.5/gpt-image-1.5-image-generation):
#: size = 1:1 / 2:3 / 3:2 或 1024x1024 / 1024x1536 / 1536x1024;quality low / medium / high(**默认 high**);
#: 参考图 1–16 张;n 目前只支持 1;提示词上限 2000 token(沿用此前的 2000 字)。
EVOLINK_GPT_IMAGE_15_CAPABILITIES = {
    "modes": ["text-to-image", "image-to-image"],
    "max_prompt_chars": 2000,
    "parameter_keys": ["size", "reference_image", "quality"],
    "parameter_choices": {"quality": ["low", "medium", "high"]},
    "default_quality": "low",
    "sizes": ["1:1", "2:3", "3:2", "1024x1024", "1024x1536", "1536x1024"],
    "default_size": "1:1",
    "source_limits": {"reference_image": 16},
    "max_num_images": 1,
}
