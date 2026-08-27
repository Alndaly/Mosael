from __future__ import annotations

from typing import Any

#: 一份素材**能给几份**,按角色分开算。描述符里写 `source_limits`,校验在
#: domain/generation/operations.validate_against_capabilities 里统一做。
#:
#: 这些数字全部来自接口自己的报错(见 tests/test_capabilities_match_reality.py 里的原话),
#: 不是从文档抄的「建议值」—— 此前一个都没写,于是界面上想挂几张挂几张,超了就是一个
#: 提交期 400,而错误信息是英文的、说的是 `content` 数组下标。
#:
#: **首尾帧组和参考素材组互斥**,写在 `exclusive_source_groups` 里:同一次生成只能用其中
#: 一组。这不是我们加的规矩,是火山原话 `first/last frame content cannot be mixed with
#: reference media content`;可灵那边的说法是「不支持仅尾帧图生视频」,所以尾帧还额外
#: 依赖首帧(见各家描述符里的 `requires_source`)。
KEYFRAME_GROUP = ["first_frame", "last_frame"]
REFERENCE_GROUP = ["reference_image", "reference_video", "reference_audio"]

#: 火山 Seedance 2 与 MiniMax H3 给的数字**一模一样**(9 / 3 / 3),两家的报错措辞不同但
#: 结论相同,所以这里合成一份共用常量,而不是抄两遍。
REFERENCE_SCENE_LIMITS = {"reference_image": 9, "reference_video": 3, "reference_audio": 3}



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
    "parameter_keys": ["size", "num_images", "reference_image"],
    "sizes": ["1024x1024", "1536x1024", "1024x1536", "1280x720", "720x1280", "1920x1088"],
    "default_size": "1024x1024",
    "size_multiple_of": 16,
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

#: 万相(通义)视频。**尺寸用 `宽*高` 而不是 480p 这种档位名** —— 百炼收的就是像素对。
#:
#: 这份清单是接口自己报的(2026-08-27 真机):传一个不在里面的尺寸,任务会失败并回一句
#: `size must be in 1080*1920,1920*1080,1440*1440,1632*1248,1248*1632,480*832,832*480,624*624`。
#: 此前写的四个里有**两个是错的**(`1280*720` / `720*1280` 不在清单里,选了必然失败),
#: 另外六个一个都没写 —— 包括 1080p。
#:
#: **万相提交时不校验参数**,跑起来才拒。所以探它的能力必须等任务终态,只看提交响应会
#: 把每一个参数都当成"支持"(时长那条就是这么错的:3/8 秒提交都返回 200,跑起来才回
#: `duration customization is not supported`)。
WAN_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video"],
    "endpoint": "dashscope",
    "parameter_keys": ["duration_seconds", "size", "first_frame"],
    "duration_seconds": [5],
    "default_duration_seconds": 5,
    "sizes": [
        "832*480",
        "480*832",
        "624*624",
        "1920*1080",
        "1080*1920",
        "1440*1440",
        "1632*1248",
        "1248*1632",
    ],
    "default_size": "832*480",
    "max_duration_seconds": 5,
    "supports_audio": False,
}

#: 万相 2.7 是**另一份契约**,不是 2.5 的参数微调 —— 2026-08-27 拿用户自己的密钥跑到终态核过:
#:
#: * 素材走 `input.media` 数组(每项 `{"type": ..., "url": ...}`),不再是 `input.img_url`。
#:   拿 2.5 的形状打 2.7,提交返回 200,任务终态才回 `Field required: input.media` ——
#:   也就是说**我们目录里挂着的 wan2.7-i2v 此前一次都没成功过**,而界面上看不出来。
#: * 时长是 **2–15 的整数区间**(`Duration should be between 2 and 15`),不是固定 5 秒。
#: * 清晰度只有 **720P / 1080P**(`Input should be '1080P' or '720P'`),不再按 W*H 给尺寸。
#:
#: 已实跑通过:t2v 2s/15s/1080P、i2v 首帧、i2v 首帧+尾帧、r2v 参考图,全部 SUCCEEDED。
WAN_27_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"],
    "endpoint": "dashscope",
    "payload_shape": "media",
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "first_frame", "last_frame", "reference_image", "reference_video",
        "first_clip",
    ],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720P", "1080P"],
    "default_resolution": "1080P",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    "default_aspect_ratio": "16:9",
    # 文档原话:参考图像 + 参考视频合计不超过 5 个,首帧图像最多 1 张。这一组和火山那边的
    # 9/3/3 不是一个数,别照抄 —— 每家自己一套。
    "source_limits": {"first_frame": 1, "last_frame": 1, "reference_image": 5, "reference_video": 5, "first_clip": 1},
    # 续写是第三条路:给一段现成的片子,让模型接着往下拍。它既不是首尾帧(那是画面的起止),
    # 也不是参考视频(那只提供风格和主体、自己不出现在成片里),所以自成一组。
    "exclusive_source_groups": [KEYFRAME_GROUP, REFERENCE_GROUP, ["first_clip"]],
    "min_duration_seconds": 2,
    "max_duration_seconds": 15,
    "supports_audio": True,
}

#: 万相视频编辑 wan2.7-videoedit。真机跑到 succeeded(2026-08-27):给一段视频加一句指令
#: (「把画面改成水彩画风格」),出的是同一段片子改过之后的样子。
#:
#: 和「参考生视频」是两回事:参考视频只提供风格和主体,成片是新拍的;这里输出的就是**这一段**。
#: 所以角色叫 source_video 而不是 reference_video,两者混用的话用户选了编辑却拿到一段重拍的片子。
#:
#: 文档原话:输入视频「有且仅有 1 个」,mp4/mov,2～10 秒,不超过 100MB;时长 [2, 10] 整数。
#: 可以再挂参考图做「指令 + 参考图编辑」(局部替换)—— 这一组和 source_video **不互斥**。
WAN_VIDEO_EDIT_CAPABILITIES = {
    "modes": ["video-edit"],
    "endpoint": "dashscope",
    "payload_shape": "media",
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "source_video", "reference_image"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720P", "1080P"],
    "default_resolution": "1080P",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    "default_aspect_ratio": "16:9",
    "source_limits": {"source_video": 1, "reference_image": 5},
    "requires_source": ["source_video"],
    "min_duration_seconds": 2,
    "max_duration_seconds": 10,
    "supports_audio": True,
}


#: Seedance 2 的时长是**区间,不是两个档位**。此前写的是 `[5, 10]`,于是界面只给这两个
#: 选项 —— 而真机实测 4 到 15 秒的任意整数都收(3 秒和 16 秒各自被拒成
#: `the specified duration is not supported`)。枚举留空,界面自动落到 min/max 数字框。
#: 参考素材那一组是 2026-08-27 对着方舟真机探出来的,每个数字都有接口原话垫底:
#:   `expected at most 9 reference images but got 10 instead`
#:   `expected at most 3 video contents but got 4 instead`
#:   `expected at most 3 audio contents but got 4 instead`
#:   `expected at most one first frame image content but got 2 instead`
#:   `first/last frame content cannot be mixed with reference media content`
#:   `reference_audio cannot be the only reference input`
#: 输入类型的白名单也是它自己给的:`text`, `image_url`, `audio_url`, `video_url`, `draft_task`。
SEEDANCE_2_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"],
    "endpoint": "ark",
    "parameter_keys": [
        "duration_seconds", "resolution",
        "first_frame", "last_frame",
        "reference_image", "reference_video", "reference_audio",
    ],
    "source_limits": {"first_frame": 1, "last_frame": 1, **REFERENCE_SCENE_LIMITS},
    "exclusive_source_groups": [KEYFRAME_GROUP, REFERENCE_GROUP],
    # 参考音频不能单独上场,得搭着参考图或参考视频给 —— 接口自己这么说的。
    "requires_companion": {"reference_audio": ["reference_image", "reference_video"]},
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "720p",
    "min_duration_seconds": 4,
    "max_duration_seconds": 15,
    "supports_audio": True,
}

#: Seedance 1 真机核过(2026-08-27),三处和此前写的不一样:
#:
#: 1. **它在方舟上,不在 LAS。** 拿方舟密钥打 LAS 直接 401 —— 那是另一套凭据,而我们只让
#:    用户配一份火山密钥。同一把密钥打方舟的 `doubao-seedance-1-0-pro-250528`,2 秒到 12 秒
#:    的任务全部跑到 succeeded。
#: 2. **时长是 2–12 的整数区间,不是 [5, 10] 两个档。** 边界是接口自己划的:
#:    `duration ... must be greater than or equal to 2` / `must be less than or equal to 12`。
#: 3. **它按分辨率出片,不是按宽高比。** `2k` 被拒(`resolution ... is not valid for model
#:    doubao-seedance-1-0-pro in t2v`),480p/720p/1080p 都过。
#:
#: 尾帧不支持:给了尾帧回的是 `last frame image content cannot be mixed with first frame or
#: reference image content` —— 也就是这一代只认首帧。
SEEDANCE_1_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video"],
    "endpoint": "ark",
    "parameter_keys": ["duration_seconds", "resolution", "first_frame"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "720p",
    "source_limits": {"first_frame": 1},
    "min_duration_seconds": 2,
    "max_duration_seconds": 12,
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
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"],
    "parameter_keys": [
        "duration_seconds",
        "resolution",
        "aspect_ratio",
        "first_frame",
        "last_frame",
        "reference_image",
        "reference_video",
        "reference_audio",
    ],
    # 同日同法核过。MiniMax 的报错是中文的,数字和火山完全一致:
    #   `reference 场景参考图最多 9 张` / `参考视频最多 3 个` / `参考音频最多 3 段`
    # 它的输入类型白名单也一样:`allowed: text|image_url|video_url|audio_url`。
    "source_limits": {"first_frame": 1, "last_frame": 1, **REFERENCE_SCENE_LIMITS},
    "exclusive_source_groups": [KEYFRAME_GROUP, REFERENCE_GROUP],
    # 真机核过(2026-08-27,MiniMax-H3 的 /v2/video_generation)。两份清单都是接口自己报的:
    #   `supported durations: 4s, 5s, 6s, 7s, 8s, 9s, 10s, 11s, 12s, 13s, 14s, 15s`
    #   `supported resolutions: 768P, 2K`
    # 此前时长只写了四个(4/6/10/15),十二个里漏了八个;分辨率只写了 2K,漏了 768P ——
    # 而 768P 是**跑得快、便宜**的那一档,做草稿时正该用它。
    "duration_seconds": [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    "default_duration_seconds": 6,
    "resolutions": ["768P", "2K"],
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
        "id": "alibaba:wan2.7-t2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-t2v",
        "capabilities": WAN_27_VIDEO_CAPABILITIES,
    },
    {
        "id": "alibaba:wan2.7-i2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-i2v",
        "capabilities": WAN_27_VIDEO_CAPABILITIES,
    },
    {
        # 参考生视频:照着参考图/参考视频里的人和风格拍,而不是从某一帧开始动。
        "id": "alibaba:wan2.7-r2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-r2v",
        "capabilities": WAN_27_VIDEO_CAPABILITIES,
    },
    {
        # 视频编辑:给一段片子加一句指令,出的是同一段片子改过之后的样子。
        "id": "alibaba:wan2.7-videoedit:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-videoedit",
        "capabilities": WAN_VIDEO_EDIT_CAPABILITIES,
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
