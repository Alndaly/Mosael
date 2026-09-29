"""经 Evolink 网关的视频能力描述符(通用 t2v/i2v、Seedance 1.5 / 2.0 / 2.5、Veo 3.1 Pro)。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

#: Evolink 是一层统一媒体网关,不是又一套模型家族。下面只描述它公开目录中已经明确写出的
#: 共同协议和代表性引擎；模型 id 仍原样下发,所以用户也能在设置里手动加入目录后来新增的型号。
#: 网关公开参数允许 3–15 秒和最高 4K,但「具体型号是否有某一档」会变化。内置描述符只展示
#: 官方 quick reference 明确承诺的 1080p 常用档,手动模型则走 provider 自己的宽范围校验。
EVOLINK_VIDEO_T2V_CAPABILITIES = {
    "modes": ["text-to-video"],
    "max_prompt_chars": 5000,
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "min_duration_seconds": 3,
    "max_duration_seconds": 15,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "1080p",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
    "default_aspect_ratio": "16:9",
}

EVOLINK_VIDEO_I2V_CAPABILITIES = {
    **EVOLINK_VIDEO_T2V_CAPABILITIES,
    "modes": ["text-to-video", "image-to-video"],
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio", "first_frame",
    ],
    "source_limits": {"first_frame": 1},
}

EVOLINK_SEEDANCE_15_CAPABILITIES = {
    **EVOLINK_VIDEO_I2V_CAPABILITIES,
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video"],
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio", "first_frame", "last_frame", "generate_audio",
    ],
    "boolean_parameters": ["generate_audio"],
    "source_limits": {"first_frame": 1, "last_frame": 1},
    # Evolink 按**张数与位置**认图(文档原文:0 张 = 文生、1 张 = 图生、2 张 = 首尾帧),
    # 单独的「尾帧」会被当成首帧 —— 不是报错,是悄悄生成反的。所以尾帧必须搭着首帧给;
    # 只给首帧(单帧图生)不受这条限制。
    "requires_companion": {"last_frame": ["first_frame"]},
    "min_duration_seconds": 4,
    "max_duration_seconds": 12,
    "supports_audio": True,
    "supports_generate_audio": True,
    "default_generate_audio": True,
}

#: Seedance 2.0 在 Evolink 上和 2.5 一样，**模式属于模型 id**，不是一个模型上的运行时开关。
#: 官方网关文档（2026-09-04 核）列出标准 / Fast 各三条路：
#:
#: * ``*-text-to-video`` 只收文本；
#: * ``*-image-to-video`` 收 1～2 张图，按数组位置解释为首帧 / 首尾帧；
#: * ``*-reference-to-video`` 收最多 9 图、3 视频、3 音频，音频不能单独提交。
#:
#: 因此不能复用方舟直连的 ``SEEDANCE_2_VIDEO_CAPABILITIES``：方舟用一个 model id + role
#: 区分模式，而 Evolink 用六个 model id + 三个媒体数组。把两者混成一份，纯文生会长出素材槽，
#: 图生又无法表达「首帧必填」，最终不是 400 就是素材被静默忽略。
EVOLINK_SEEDANCE_20_BASE = {
    "max_prompt_chars": 5000,
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "min_duration_seconds": 4,
    "max_duration_seconds": 15,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "720p",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"],
    "default_aspect_ratio": "16:9",
    "supports_audio": True,
    "supports_generate_audio": True,
    "default_generate_audio": True,
    "boolean_parameters": ["generate_audio"],
}

EVOLINK_SEEDANCE_20_T2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_20_BASE,
    "modes": ["text-to-video"],
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "generate_audio"],
}

EVOLINK_SEEDANCE_20_I2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_20_BASE,
    "modes": ["image-to-video", "keyframes-to-video"],
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio", "first_frame", "last_frame", "generate_audio",
    ],
    "source_limits": {"first_frame": 1, "last_frame": 1},
    "requires_source": [["first_frame"]],
    "requires_companion": {"last_frame": ["first_frame"]},
}

EVOLINK_SEEDANCE_20_R2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_20_BASE,
    "modes": ["reference-to-video"],
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "reference_image", "reference_video", "reference_audio", "generate_audio",
    ],
    "source_limits": {"reference_image": 9, "reference_video": 3, "reference_audio": 3},
    "requires_companion": {"reference_audio": ["reference_image", "reference_video"]},
}

#: Fast 的输入协议和标准版一致，但网关只承诺 480p / 720p；不能让它继承标准版的 1080p。
EVOLINK_SEEDANCE_20_FAST_T2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_20_T2V_CAPABILITIES,
    "resolutions": ["480p", "720p"],
}

EVOLINK_SEEDANCE_20_FAST_I2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_20_I2V_CAPABILITIES,
    "resolutions": ["480p", "720p"],
}

EVOLINK_SEEDANCE_20_FAST_R2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_20_R2V_CAPABILITIES,
    "resolutions": ["480p", "720p"],
}

#: Seedance 2.5 在 Evolink 上是**五个模型 id,模式在名字里而不是参数里**
#: (逐字核过 2026-09-01 的五份 OpenAPI:seedance-2.5-{text,image,reference}-to-video 与
#: video-{edit,extend})。所以每个 id 一份描述符,而不是一份描述符加一个模式开关 ——
#: 后者正是「只有首尾帧模式」那个错觉的来源:加了 -image-to-video 的人拿不到参考模式。
#: 五份共用:480p/720p/1080p 默认 720p、prompt 上限 10000 token、generate_audio 默认开。
EVOLINK_SEEDANCE_25_BASE = {
    "max_prompt_chars": 10000,
    "resolutions": ["480p", "720p", "1080p"],
    "default_resolution": "720p",
    "supports_audio": True,
    "supports_generate_audio": True,
    "default_generate_audio": True,
    "boolean_parameters": ["generate_audio"],
}

#: 2.5 的时长是 4–30 秒任意整数,另有 `-1` = 自动(按实际出片计费)。两者分别由区间与
#: `duration_special_values` 表达，三个 UI 与 MCP 都读取同一份。
EVOLINK_SEEDANCE_25_DURATION = {
    "duration_seconds": [],
    "duration_special_values": [-1],
    "default_duration_seconds": 5,
    "min_duration_seconds": 4,
    "max_duration_seconds": 30,
}

EVOLINK_SEEDANCE_25_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"]

EVOLINK_SEEDANCE_25_T2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_25_BASE,
    **EVOLINK_SEEDANCE_25_DURATION,
    "modes": ["text-to-video"],
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "generate_audio"],
    # 文档原文:text-to-video only,does not support image/video/audio input —— 不声明任何
    # 素材角色,挂了素材的那条路在提交前就被自己的校验拦下,而不是发给网关吃 400。
    "aspect_ratios": EVOLINK_SEEDANCE_25_RATIOS,
    "default_aspect_ratio": "adaptive",
}

EVOLINK_SEEDANCE_25_I2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_25_BASE,
    **EVOLINK_SEEDANCE_25_DURATION,
    "modes": ["image-to-video", "keyframes-to-video"],
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "first_frame", "last_frame", "generate_audio"],
    # 文档原文:image_urls 必填、1–2 张,1 张自动为首帧、2 张按位置为首帧+尾帧。
    # 位置语义下「只给尾帧」会被当成首帧,所以首帧必填、尾帧可选(单帧图生不受影响)。
    "source_limits": {"first_frame": 1, "last_frame": 1},
    "requires_source": [["first_frame"]],
    # 文档原文:the only value this model accepts —— 固定比例发过去就是 400。
    "aspect_ratios": ["adaptive"],
    "default_aspect_ratio": "adaptive",
}

EVOLINK_SEEDANCE_25_R2V_CAPABILITIES = {
    **EVOLINK_SEEDANCE_25_BASE,
    **EVOLINK_SEEDANCE_25_DURATION,
    "modes": ["reference-to-video"],
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "reference_image", "reference_video", "reference_audio", "generate_audio",
    ],
    # 文档原文:图 1–30 / 视频 1–10 / 音频 1–10,三者**至少给一份**。提示词里用
    # @image1/@video1/@audio1 指认素材,编号跟着各自数组的顺序走。
    "source_limits": {"reference_image": 30, "reference_video": 10, "reference_audio": 10},
    "requires_source": [["reference_image", "reference_video", "reference_audio"]],
    "aspect_ratios": EVOLINK_SEEDANCE_25_RATIOS,
    "default_aspect_ratio": "adaptive",
}

#: edit / extend 的视频数组**第一位永远是被处理的那一段**(文档原文:the first video is
#: the video being edited / extended),其余位置才算参考 —— 所以待编辑/待续写必填且限一份,
#: 视频总数上限 10,参考视频的上限因此是 9。两条路的宽高比都只收 adaptive(跟随输入)。
EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES = {
    **EVOLINK_SEEDANCE_25_BASE,
    "modes": ["video-edit"],
    # 时长只收 -1(跟随输入;文档原文 only -1 is supported,自定义时长会被拒)。它作为特殊
    # 值显式声明，界面显示“自动”，Adapter 也原样发送，不能依赖网关默认值碰巧相同。
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "source_video", "reference_image", "reference_video", "reference_audio", "generate_audio",
    ],
    "duration_seconds": [],
    "duration_special_values": [-1],
    "default_duration_seconds": -1,
    "source_limits": {"source_video": 1, "reference_image": 30, "reference_video": 9, "reference_audio": 10},
    "requires_source": [["source_video"]],
    "aspect_ratios": ["adaptive"],
    "default_aspect_ratio": "adaptive",
}

EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES = {
    **EVOLINK_SEEDANCE_25_BASE,
    **EVOLINK_SEEDANCE_25_DURATION,
    "modes": ["video-extend"],
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "first_clip", "reference_image", "reference_video", "reference_audio", "generate_audio",
    ],
    "source_limits": {"first_clip": 1, "reference_image": 30, "reference_video": 9, "reference_audio": 10},
    "requires_source": [["first_clip"]],
    "aspect_ratios": ["adaptive"],
    "default_aspect_ratio": "adaptive",
}

#: Veo 3.1 Pro 经 Evolink:和那边的文生视频同形,只是原生带音频。**单独一份而不是就地拼**——
#: 就地 `{**X, ...}` 拼出来的是个匿名对象,名册里指不到它,用户也就没法选它。
EVOLINK_VEO_31_PRO_CAPABILITIES = {**EVOLINK_VIDEO_T2V_CAPABILITIES, "supports_audio": True}
