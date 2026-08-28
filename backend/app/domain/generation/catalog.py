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
#: 每种素材角色**叫什么、是干什么的**。一份,三个消费者:提交前的校验拿它写报错、
#: 智能体拿它知道每个参数该给什么、界面拿它做标题。
#:
#: 此前这张表存在三份(operations 的中文名、mcp_server 的说明、前端的 ROLE_COPY),而
#: 新增角色时漏掉哪一份都不会报错 —— 只是智能体不知道有这个东西,于是永远不会用它。
#: 事实上到这次为止,mcp_server 那份就漏了参考音频、待编辑的视频、待续写的片段、驱动音频四种。
SOURCE_ROLE_LABELS = {
    "first_frame": "首帧",
    "last_frame": "尾帧",
    "reference_image": "参考图",
    "reference_video": "参考视频",
    "reference_audio": "参考音频",
    "source_video": "待编辑的视频",
    "first_clip": "待续写的片段",
    "driving_audio": "驱动音频",
}

#: 给智能体的一句话:这个角色到底是什么意思。**光有名字不够** —— 「参考视频」和「待编辑的
#: 视频」都是视频,分不清的话它会拿编辑模型去做参考生成,而画面出得来、只是不是那一段。
SOURCE_ROLE_HELP = {
    "first_frame": "成片的第一格画面;asset_id 或 first_frame_url 外链",
    "last_frame": "成片的最后一格;要和首帧一起给,单独给尾帧不成立",
    "reference_image": "照着它的风格和主体来拍;它自己一帧都不出现在成片里",
    "reference_video": "照着它的风格和主体来拍;成片是新的,不是它",
    "reference_audio": "参考音色/风格,不驱动画面",
    "source_video": "**被编辑的那一段**;成片就是它改过之后的样子",
    "first_clip": "**被接着往下拍的那一段**;成片以它开头,总时长要比它长",
    "driving_audio": "画面跟着它走 —— 口型同步、动作卡点",
}

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
    "parameter_keys": ["size", "num_images", "seed", "negative_prompt"],
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
    "parameter_keys": ["size", "num_images", "seed", "negative_prompt", "reference_image"],
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
    "source_limits": {"first_frame": 1},
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
#: 万相 2.7 的三个型号**各认各的素材**,不是一份描述符能盖住的。类型白名单是接口自己报的
#: (2026-08-27 真机,每条都跑到终态):
#:
#:   i2v  `Input should be 'first_frame', 'last_frame', 'driving_audio' or 'first_clip'`
#:   r2v  `Input should be 'reference_image', 'reference_video' or 'first_frame'`
#:   t2v  **给什么都收,而且照样 SUCCEEDED** —— 它根本不看 media。
#:
#: 最后那条最要命:此前三个型号共用一份描述符,于是文生视频那一栏也长出了首帧和参考图。
#: 用户挂上一张图、任务成功、片子里没有那张图的任何痕迹 —— 不报错,只是那张图从来没被用过。
#: 所以 t2v 一个素材角色都不声明。
WAN_27_T2V_CAPABILITIES = {
    "modes": ["text-to-video"],
    "endpoint": "dashscope",
    "payload_shape": "media",
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720P", "1080P"],
    "default_resolution": "1080P",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    "default_aspect_ratio": "16:9",
    "min_duration_seconds": 2,
    "max_duration_seconds": 15,
    "supports_audio": True,
}

#: 图生视频。文档说它一个模型干三件事:首帧生视频、首尾帧生视频、**视频续写**。
#:
#: 素材组合是**白名单**,不是随便配 —— 文档原话「仅支持以下特定的素材组合,非法组合将报错」:
#:   first_frame / first_frame+driving_audio / first_frame+last_frame /
#:   first_frame+last_frame+driving_audio / first_clip / first_clip+last_frame
#:
#: 这份白名单用现有的两条规则就能原样表达,不用再造一个机制:
#:   * 首帧和续写片段互斥(一个是从这张图动起来,一个是接着这段片子往下拍);
#:   * 尾帧得搭首帧或续写片段(光给尾帧没有起点);
#:   * driving_audio 只跟首帧走(所以续写 + 音频这个非法组合自动落空)。
WAN_27_I2V_CAPABILITIES = {
    "modes": ["image-to-video", "keyframes-to-video", "video-extend"],
    "endpoint": "dashscope",
    "payload_shape": "media",
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "first_frame", "last_frame", "first_clip", "driving_audio",
    ],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720P", "1080P"],
    "default_resolution": "1080P",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    "default_aspect_ratio": "16:9",
    # 文档原话:每种 type 在 media 数组中最多出现一次。
    "source_limits": {"first_frame": 1, "last_frame": 1, "first_clip": 1, "driving_audio": 1},
    "requires_source": [["first_frame", "first_clip"]],
    "exclusive_source_groups": [["first_frame"], ["first_clip"]],
    "requires_companion": {
        "last_frame": ["first_frame", "first_clip"],
        "driving_audio": ["first_frame"],
    },
    "min_duration_seconds": 2,
    "max_duration_seconds": 15,
    "supports_audio": True,
}

#: 参考生视频。接口两句话把规矩说全了:
#:   `Field required: input.media`      —— 必须给参考素材,不能空着跑
#:   `Only first frame provided is not allowed` —— 光给首帧不算,首帧只是**辅助**
#:
#: 所以这里的首帧和 i2v 那边的首帧不是一回事:那边它是主角(画面从它动起来),这边它得
#: 搭着参考素材才有意义。
WAN_27_R2V_CAPABILITIES = {
    "modes": ["reference-to-video"],
    "endpoint": "dashscope",
    "payload_shape": "media",
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "reference_image", "reference_video", "first_frame",
    ],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720P", "1080P"],
    "default_resolution": "1080P",
    "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    "default_aspect_ratio": "16:9",
    # 文档原话:参考图像 + 参考视频合计不超过 5 个,首帧图像最多 1 张。这一组和火山那边的
    # 9/3/3 不是一个数,别照抄 —— 每家自己一套。
    "source_limits": {"reference_image": 5, "reference_video": 5, "first_frame": 1},
    "requires_source": [["reference_image", "reference_video"]],
    # 带参考视频时时长压到 10 秒(文档原话:包含参考视频 2–10s,不包含 2–15s)。写死 15 的话,
    # 用户挂了参考视频再选 12 秒,要等任务失败才知道。
    "conditional_max_duration_seconds": {"reference_video": 10},
    "min_duration_seconds": 2,
    "max_duration_seconds": 15,
    "supports_audio": True,
}

#: 可灵 2.x 那一代(旧接口 `/v1/videos/image2video`)。参数是平铺的,只有首尾帧。
KLING_LEGACY_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video"],
    "parameter_keys": ["duration_seconds", "aspect_ratio", "first_frame", "last_frame", "negative_prompt"],
    "duration_seconds": [5, 10],
    "default_duration_seconds": 5,
    "aspect_ratios": ["16:9", "9:16", "1:1"],
    "default_aspect_ratio": "16:9",
    "source_limits": {"first_frame": 1, "last_frame": 1},
    "requires_companion": {"last_frame": ["first_frame"]},
    "max_duration_seconds": 10,
}

#: 可灵 3.0(新接口 `/image-to-video/kling-3.0`,请求体是 contents 数组)。
#:
#: **多图参考在这一代才有,而且不是「挂几张图」。** 可灵要你先用 2～4 张图建一个**主体**
#: (进主体库、有名字、能复用),生成时引用它的 id,提示词里用 `@名字` 点名;一次最多引 3 个。
#: 这一步由适配器代劳(见 ai/providers/video/kling_elements):界面上照旧是挂参考图,
#: 底下自动查/建主体。所以这里的 `reference_image` 上限是 4 —— 那是**一个主体**的取图上限,
#: 不是别家那种"这次生成用几张图"。
#:
#: 数字来自官方能力地图与 3.0 图生视频的 API 参考(2026-08-27):时长 3～15 的整数,
#: 清晰度 720p/1080p/**4k**,首帧尾帧各 1 张且不支持仅尾帧。
#:
#: **没有可灵密钥可核。** 这一份是照文档写的,不是真机探的 —— 和上面几家不一样,别把它
#: 当成同等确信的东西:等有密钥了要按 test_capabilities_match_reality 的法子重核一遍。
KLING_V3_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"],
    "payload_shape": "contents",
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio", "negative_prompt",
        "first_frame", "last_frame", "reference_image",
        "generate_audio", "multi_shot",
    ],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720p", "1080p", "4k"],
    "default_resolution": "720p",
    "aspect_ratios": ["16:9", "9:16", "1:1"],
    "default_aspect_ratio": "16:9",
    "source_limits": {"first_frame": 1, "last_frame": 1, "reference_image": 4},
    # 建主体要 1 张正面图 + 1～3 张其他角度,少于两张建不起来。
    "min_reference_images": 2,
    "requires_companion": {"last_frame": ["first_frame"]},
    "min_duration_seconds": 3,
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
    "requires_source": [["source_video"]],
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
#: 方舟视频的宽高比。**官方文档原话**(docs.volcengine.com/docs/82379/1520757,2026-08-28 查):
#:   可选值:16:9、4:3、1:1、3:4、9:16、21:9、adaptive(根据任务类型和输入内容自动适配宽高比)
#: 默认值分模型:Seedance 2.5 / 2.0 系列 / 1.5 pro 默认 `adaptive`;1.0 pro 与 1.0 pro fast
#: **文生视频默认 16:9、图生视频默认 adaptive**。
#: 首帧/首尾帧生视频时模型自动保持与首帧图片一致 —— 所以那条路上根本不用传它。
ARK_VIDEO_RATIOS = ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]

SEEDANCE_2_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"],
    "endpoint": "ark",
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "first_frame", "last_frame",
        "reference_image", "reference_video", "reference_audio",
    ],
    "source_limits": {"first_frame": 1, "last_frame": 1, **REFERENCE_SCENE_LIMITS},
    "exclusive_source_groups": [KEYFRAME_GROUP, REFERENCE_GROUP],
    # 参考音频不能单独上场,得搭着参考图或参考视频给 —— 接口自己这么说的。
    "requires_companion": {"reference_audio": ["reference_image", "reference_video"]},
    "duration_seconds": [],
    "default_duration_seconds": 5,
    # 文档:Seedance 2.0 默认 720p,可选 480p/720p/1080p/**4k**。fast 与 mini 只到 720p,
    # 它们各自有自己的描述符(见下)—— 此前三个共用这一份,于是 fast/mini 上也列出 1080p,
    # 选了必然失败。08-27 那次真机核的是 2.0 base,fast/mini 是**继承**来的,没被验证过。
    "resolutions": ["480p", "720p", "1080p", "4k"],
    "default_resolution": "720p",
    "aspect_ratios": ARK_VIDEO_RATIOS,
    "default_aspect_ratio": "adaptive",
    "min_duration_seconds": 4,
    "max_duration_seconds": 15,
    "supports_audio": True,
}

#: 2.0 fast / mini:除了**分辨率只到 720p**,其余和 2.0 base 一样(文档原话:
#: 「Seedance 2.0 fast:默认值 720p;可选值 480p、720p」,mini 同)。
SEEDANCE_2_SMALL_VIDEO_CAPABILITIES = {
    **SEEDANCE_2_VIDEO_CAPABILITIES,
    "resolutions": ["480p", "720p"],
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
    # seed / camera_fixed 是文档明确写「Seedance 1.5 pro / 1.0 pro / 1.0 pro fast」支持的两项,
    # **2.0 系列不在支持名单里** —— 所以它们只挂在 1.x 这一族。
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "seed", "camera_fixed", "first_frame"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["480p", "720p", "1080p"],
    # 文档:1.0 pro 与 1.0 pro fast 默认 **1080p**(不是 720p)。
    "default_resolution": "1080p",
    "aspect_ratios": ARK_VIDEO_RATIOS,
    # 文档:1.0 pro / fast 是「文生视频默认 16:9,图生视频默认 adaptive」。这里给文生那一档的
    # 默认值 —— 有首帧时我们根本不传 ratio,交给模型按图片适配(见 providers/video/seedance)。
    "default_aspect_ratio": "16:9",
    "source_limits": {"first_frame": 1},
    "min_duration_seconds": 2,
    "max_duration_seconds": 12,
    "supports_audio": False,
}

#: Seedance 1.5 pro **不是 1.0 的一个别名**,规格自己一套(文档 2026-08-28 查):
#:   · 时长 [4, 12] —— 下限是 4 不是 2。此前它共用 1.0 那份,写着下限 2,而 08-27 的真机
#:     核的是 **1.0 pro**(接口原话 `must be greater than or equal to 2`),1.5 从没被验证过。
#:     于是界面允许选 2 秒、3 秒,提交到方舟才失败。
#:   · 默认分辨率 720p(1.0 那两个是 1080p)。
#:   · 有声视频:文档把 1.5 pro 列进 generate_audio 的支持名单。
SEEDANCE_15_VIDEO_CAPABILITIES = {
    **SEEDANCE_1_VIDEO_CAPABILITIES,
    "min_duration_seconds": 4,
    "default_resolution": "720p",
    "default_aspect_ratio": "adaptive",
    "supports_audio": True,
}


COMFYUI_IMAGE_CAPABILITIES = {
    "modes": ["text-to-image"],
    "max_prompt_chars": 8000,
    # workflow / workflow_params:**选一个 ComfyUI 里保存的工作流**,以及它那张动态参数表单。
    # 适配器一直读这两个键(providers/comfyui/provider),界面也一直在发,只是描述符没声明 ——
    # 于是校验器把它们当成"这个模型不支持的参数"当场拦下:选了工作流就提交不了,而选工作流
    # 正是接 ComfyUI 的理由。没有测试覆盖"带工作流提交",所以一直是绿的。
    "parameter_keys": ["size", "seed", "steps", "negative_prompt", "workflow", "workflow_params"],
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
    # 同上 —— 视频这边界面只发 workflow_params(workflow 那一半漏在 image 分支里,见下),
    # 两个都得声明,否则选了工作流照样提交不了。
    "parameter_keys": ["duration_seconds", "seed", "negative_prompt", "workflow", "workflow_params"],
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
        "capabilities": WAN_27_T2V_CAPABILITIES,
    },
    {
        "id": "alibaba:wan2.7-i2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-i2v",
        "capabilities": WAN_27_I2V_CAPABILITIES,
    },
    {
        # 参考生视频:照着参考图/参考视频里的人和风格拍,而不是从某一帧开始动。
        "id": "alibaba:wan2.7-r2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.7-r2v",
        "capabilities": WAN_27_R2V_CAPABILITIES,
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
        "capabilities": SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-2-0-mini-260615:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-mini-260615",
        "capabilities": SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
    },
    {
        "id": "bytedance:doubao-seedance-1-5-pro-251215:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-5-pro-251215",
        "capabilities": SEEDANCE_15_VIDEO_CAPABILITIES,
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
            # 没有 Google 密钥,这一份仍是照文档写的 —— Veo 3.x 文档上还有参考图和续写,
            # 都没接,等有密钥再核。
            "source_limits": {"first_frame": 1},
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
        # 旧接口那一代(2.x):参数平铺,只有首尾帧,没有主体。
        "id": "kuaishou:kling:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling",
        "capabilities": KLING_LEGACY_VIDEO_CAPABILITIES,
    },
    {
        "id": "kuaishou:kling-v3:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling-v3",
        "capabilities": KLING_V3_VIDEO_CAPABILITIES,
    },
    {
        "id": "kuaishou:kling-v3-omni:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling-v3-omni",
        "capabilities": KLING_V3_VIDEO_CAPABILITIES,
    },
    {
        "id": "kuaishou:kling-3.0-turbo:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling-3.0-turbo",
        "capabilities": KLING_V3_VIDEO_CAPABILITIES,
    },
]

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
