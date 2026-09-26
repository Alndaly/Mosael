from __future__ import annotations

from typing import Any

#: **生成的种类**:图像、视频、音频。全仓只有这一份 —— 解析、设置页、参数组表单、插件目录、
#: 画板的「生成」产出者都从这里读。此前 `("image", "video")` 在七个文件里各抄一份,于是
#: 加一种介质要记得改七处,漏掉的那一处不会报错,只会让那一种在某个入口上悄悄不见。
#:
#: 音频(音乐、BGM、歌曲、音效、给视频配声)是**生成**的一种,和语音合成(念一段字,
#: voices/speak 那条路)不是一回事 —— 见 ADR 0022。
GENERATION_KINDS = ("image", "video", "audio")

#: 一个模型对**提示词**的要求 —— 描述符的 `prompt` 格子,三种取值,没写就是 `required`:
#:
#: - `required`:要写一段描述。会唱歌词的模型(参数里有 `lyrics`)只给歌词也行 —— 歌词本身就是
#:   「写一首什么样的歌」;
#: - `optional`:可以不写。给视频配声、按素材出结果的模型,写了是锦上添花;
#: - `none`:这个模型**不收**提示词(ComfyUI 里的放大、抠图这类工作流)。写了也不会生效,所以
#:   提交时带着提示词是错 —— 当场说,而不是让人以为那句话起了作用。
#:
#: **一个格子、一套规矩**(operations.validate_text_inputs),不按种类分支:此前图像 / 视频「必须有
#: 提示词」写死在契约层,音频另有「必须写描述」「可以不写描述」两个布尔,于是插件里一张
#: 不需要提示词的放大工作流,也逼着人先敲一句没用的话。三个界面(AI 工作台、画板、工作流节点)
#: 和智能体都照这一格摆提示词框、判能不能提交。
PROMPT_MODES = ("required", "optional", "none")


def prompt_mode(capabilities: dict[str, Any] | None) -> str:
    """这个描述符对提示词的要求。没写(或写了认不出的值)就是 `required` —— 保守的那一边。"""
    value = (capabilities or {}).get("prompt")
    return value if value in PROMPT_MODES else "required"


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
    "mask": "蒙版",
}

#: 给智能体的一句话:这个角色到底是什么意思。**光有名字不够** —— 「参考视频」和「待编辑的
#: 视频」都是视频,分不清的话它会拿编辑模型去做参考生成,而画面出得来、只是不是那一段。
SOURCE_ROLE_HELP = {
    "first_frame": "成片的第一格画面;asset_id 或 first_frame_url 外链",
    "last_frame": "成片的最后一格;有的模型要求它和首帧一起给(看各模型自己的规矩),有的可以单独给",
    "reference_image": "照着它的风格和主体来拍;它自己一帧都不出现在成片里",
    "reference_video": "照着它的风格和主体来拍;成片是新的,不是它",
    "reference_audio": "参考音色/风格,不驱动画面;生成音乐时是「照这首的风格来」",
    "source_video": "**被处理的那一段视频**;视频编辑时成片是它改过之后的样子,生成音频时产出的声音按它的画面对齐",
    "first_clip": "**被接着往下拍/往下写的那一段**;成片以它开头,总时长要比它长(音频续写时是一段音频)",
    "driving_audio": "画面跟着它走 —— 口型同步、动作卡点",
    "mask": "局部重绘的蒙版:白色是要改的地方,和要改的那张图(参考图)一起给",
}

KEYFRAME_GROUP = ["first_frame", "last_frame"]
REFERENCE_GROUP = ["reference_image", "reference_video", "reference_audio"]

#: 「这一次用哪一组素材」。上面两组在 Seedance 这类模型上**互斥**(火山原话见下方
#: exclusive_source_groups)。整片流程里每一镜走哪条路是逐镜决定的:两组素材都接上,再由这一项
#: 选一组 —— 比为两条路各画一个生成节点、再在下游合流干净。选了一组就丢掉与它互斥的那一组,
#: 两组之外的角色(待编辑的视频、驱动音频……)不受影响。
SOURCE_GROUPS = ("all", "keyframes", "references")
SOURCE_GROUP_DROPS = {"keyframes": tuple(REFERENCE_GROUP), "references": tuple(KEYFRAME_GROUP)}

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
#: **多图参考只属于这一代的 Omni 型号,而且不是「挂几张图」。** 可灵要你先用 2～4 张图建一个**主体**
#: (进主体库、有名字、能复用),生成时引用它的 id,提示词里用 `@名字` 点名;一次最多引 3 个。
#: 这一步由适配器代劳(见 ai/providers/adapters/kuaishou/elements):界面上照旧是挂参考图,
#: 底下自动查/建主体。所以这里的 `reference_image` 上限是 4 —— 那是**一个主体**的取图上限,
#: 不是别家那种"这次生成用几张图"。
#:
#: 数字来自官方能力地图与 3.0 图生视频的 API 参考(2026-08-27):时长 3～15 的整数,
#: 清晰度 720p/1080p/**4k**,首帧尾帧各 1 张且不支持仅尾帧。
#:
#: **没有可灵密钥可核。** 这一份是照文档写的,不是真机探的 —— 和上面几家不一样,别把它
#: 当成同等确信的东西:等有密钥了要按 test_capabilities_match_reality 的法子重核一遍。
KLING_V3_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video", "keyframes-to-video"],
    "payload_shape": "contents",
    "parameter_keys": [
        "duration_seconds", "resolution", "aspect_ratio",
        "first_frame", "last_frame", "generate_audio", "multi_shot", "external_task_id",
    ],
    "boolean_parameters": ["generate_audio", "multi_shot"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["720p", "1080p", "4k"],
    "default_resolution": "720p",
    "aspect_ratios": ["16:9", "9:16", "1:1"],
    "default_aspect_ratio": "16:9",
    "source_limits": {"first_frame": 1, "last_frame": 1},
    "requires_companion": {"last_frame": ["first_frame"]},
    "min_duration_seconds": 3,
    "max_duration_seconds": 15,
    "supports_audio": True,
    "supports_generate_audio": True,
}

#: 主体参考只属于 Omni；普通版 / Turbo 挂主体不能靠 Adapter 偷偷换模型。
KLING_V3_OMNI_VIDEO_CAPABILITIES = {
    **KLING_V3_VIDEO_CAPABILITIES,
    "modes": [*KLING_V3_VIDEO_CAPABILITIES["modes"], "reference-to-video"],
    "parameter_keys": [*KLING_V3_VIDEO_CAPABILITIES["parameter_keys"], "reference_image"],
    "source_limits": {"first_frame": 1, "last_frame": 1, "reference_image": 4},
    # 当前 Adapter 先建可复用主体：1 张正面 + 1～3 张其他角度。
    "min_reference_images": 2,
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
        "reference_image", "reference_video", "reference_audio", "generate_audio",
    ],
    "boolean_parameters": ["generate_audio"],
    "source_limits": {"first_frame": 1, "last_frame": 1, **REFERENCE_SCENE_LIMITS},
    "exclusive_source_groups": [KEYFRAME_GROUP, REFERENCE_GROUP],
    # 参考音频不能单独上场,得搭着参考图或参考视频给 —— 接口自己这么说的。
    "requires_companion": {"reference_audio": ["reference_image", "reference_video"]},
    # **参考视频只能按链接交付,不能内联。** 官方文档:`image_url` 收公网 http(s) 链接、
    # Base64 data URL、以及方舟自家素材库的 `asset://<ID>`;而 `video_url` **只收前者和后者,
    # 明确不收 Base64**。接口的原话是
    # `reference_video must be provided as a web url`。
    #
    # 参考视频本身是支持的(2.0 收 3 段、2–15 秒、≤200MB、mp4/mov、H.264/H.265)——
    # 不成立的只是"把本地文件编码进请求体"这一种交付方式。
    #
    # 只写 reference_video 这一条:参考音频有没有同样的限制没核过,而这个仓库的规矩是
    # **只写有把握的**(推错比不推更糟)。哪天核到了再加。
    #
    # 本地素材怎么变成链接:装一个对象存储插件(plugins/examples 下的 volcengine-tos /
    # aliyun-oss / aws-s3 / tencent-cos),它的 `*_upload` 传上去之后交回一条**限时直链** —— 签名在查询串
    # 里,桶不必设成公共读。方舟自己的文档推荐的也是 TOS。
    "url_only_roles": ["reference_video"],
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
    "supports_generate_audio": True,
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
    "boolean_parameters": ["camera_fixed"],
    "duration_seconds": [],
    "default_duration_seconds": 5,
    "resolutions": ["480p", "720p", "1080p"],
    # 文档:1.0 pro 与 1.0 pro fast 默认 **1080p**(不是 720p)。
    "default_resolution": "1080p",
    "aspect_ratios": ARK_VIDEO_RATIOS,
    # 文档:1.0 pro / fast 是「文生视频默认 16:9,图生视频默认 adaptive」。这里给文生那一档的
    # 默认值 —— 有首帧时我们根本不传 ratio,交给模型按图片适配(见 providers/adapters/bytedance/video)。
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
    "supports_generate_audio": True,
    "parameter_keys": [*SEEDANCE_1_VIDEO_CAPABILITIES["parameter_keys"], "generate_audio"],
    "boolean_parameters": ["camera_fixed", "generate_audio"],
}


#: MiniMax 海螺 H3(2026-07)。原生 2K、4–15 秒、可给首帧;文生视频必须给具体比例,
#: 图生视频恒为 adaptive(见 ``ai/providers/adapters/minimax/video.py``)。
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

GOOGLE_VEO_VIDEO_CAPABILITIES = {
    "modes": ["text-to-video", "image-to-video"],
    "parameter_keys": ["duration_seconds", "resolution", "aspect_ratio", "first_frame", "seed"],
    # 没有 Google 密钥,这一份仍是照文档写的 —— Veo 3.x 文档上还有参考图和续写,
    # 都没接,等有密钥再核。
    "source_limits": {"first_frame": 1},
    "duration_seconds": [4, 6, 8],
    "default_duration_seconds": 8,
    "resolutions": ["720p", "1080p", "4k"],
    "default_resolution": "720p",
    "duration_by_resolution": {"1080p": [8], "4k": [8]},
    "aspect_ratios": ["16:9", "9:16"],
    "default_aspect_ratio": "16:9",
    "max_duration_seconds": 8,
    # Veo 3.x 原生生成音频；它没有 generate_audio 开关。
    "supports_audio": True,
}

#: Veo 3.1 Pro 经 Evolink:和那边的文生视频同形,只是原生带音频。**单独一份而不是就地拼**——
#: 就地 `{**X, ...}` 拼出来的是个匿名对象,名册里指不到它,用户也就没法选它。
EVOLINK_VEO_31_PRO_CAPABILITIES = {**EVOLINK_VIDEO_T2V_CAPABILITIES, "supports_audio": True}

# ─────────────────────────────────────────────────────────────────────────────────────────────
# 音频生成(音乐 / BGM / 歌曲 / 音效 / 给视频配声)。见 ADR 0022 与 docs/AUDIO_GENERATION_CAPABILITIES.md。
#
# **宿主的音频词汇**(各家 Adapter 把它翻成自己的字段,界面和智能体只认这一份):
#
#   提示词          描述想要的声音:风格、流派、情绪、乐器、速度都写在这里。各家单独的「风格」字段
#                   (Suno 的 style、火山的 Text)由 Adapter 从提示词喂 —— 不另开一个 style 键,
#                   否则同一句话要在两个框里写两遍,而两个框哪个生效要看是哪一家。
#   lyrics          歌词,一段长文字(带 [Verse] / [Chorus] 段落标签)。独立于提示词:歌词是要唱的字,
#                   提示词是怎么唱。上限 `max_lyrics_chars`。
#   instrumental    纯音乐(不要人声)。给了它就不该再给歌词(提交前拦,见 operations)。
#   duration_seconds 时长。**音频上可以不给** —— 多数音乐模型按歌词长短自己定曲长。
#   vocal_gender    人声性别偏好(female / male),Adapter 翻成各家的写法(Suno 是 f / m)。
#   title           曲名(Suno 的自定义模式要它)。
#   negative_prompt 不要什么(Suno 的 negative_tags)。
#   reference_audio 参考音频(照着它的风格 / 音色来);source_video 要配声的那段视频;reference_image 图生音乐的图。
#
# 描述符上的音频专属格子:`max_lyrics_chars`、`default_instrumental`、`lyrics_excludes_prompt`(这家
# 歌词和描述只收一段)、`requires_lyrics`、`outputs_per_request`(一次交回几首,Suno 是两首)。
# 提示词要不要写是各种生成共用的那一格 `prompt`(见文件头的 PROMPT_MODES):视频配声是 `optional`。
#
# **只收官方文档查得到的**:每一份都写了文档地址和核对日期(2026-09-25)。一个都没有真机跑过 ——
# 没有密钥可核,而这些接口按次收钱。
# ─────────────────────────────────────────────────────────────────────────────────────────────

#: 人声性别。宿主的写法是 female / male;各家的写法(Suno 的 f / m)由 Adapter 翻。
VOCAL_GENDER_SCHEMA = {"type": "string", "enum": ["female", "male"], "title": "Vocal gender"}

#: Evolink 上的 Suno。文档:https://evolink.ai/docs/en/api-manual/audio-series/suno/suno-music-generation
#: (及同名 .json 的 OpenAPI,2026-09-25 核)。**一次交回两首**(产品页 https://evolink.ai/suno)。
#:
#: Suno 有两种模式,由 Adapter 按用户给了什么选(见 adapters/evolink/generation.build_audio_payload):
#: 只有描述 → 简单模式(提示词 ≤500);给了歌词 / 纯音乐 / 负向 / 曲名 / 人声 / 时长 → 自定义模式,
#: 这时描述进 `style`(v4.5 起 ≤1000,v4 ≤200)。上限取两种模式都成立的那个数。
EVOLINK_SUNO_CAPABILITIES = {
    "modes": ["text-to-music", "lyrics-to-song", "text-to-bgm"],
    "parameter_keys": ["lyrics", "instrumental", "negative_prompt", "title", "vocal_gender"],
    "boolean_parameters": ["instrumental"],
    "default_instrumental": False,
    "max_prompt_chars": 500,
    "max_lyrics_chars": 5000,
    "outputs_per_request": 2,
    "parameter_schema": {
        "title": {"type": "string", "title": "Title"},
        "vocal_gender": VOCAL_GENDER_SCHEMA,
    },
}
#: v4:自定义模式的 style ≤200、歌词 ≤3000。
EVOLINK_SUNO_V4_CAPABILITIES = {**EVOLINK_SUNO_CAPABILITIES, "max_prompt_chars": 200, "max_lyrics_chars": 3000}
#: v5.5 才收 `duration`(10–360 秒,仅自定义模式;给了时长 Adapter 就走自定义模式)。
EVOLINK_SUNO_V55_CAPABILITIES = {
    **EVOLINK_SUNO_CAPABILITIES,
    "parameter_keys": [*EVOLINK_SUNO_CAPABILITIES["parameter_keys"], "duration_seconds"],
    "duration_seconds": [],
    "min_duration_seconds": 10,
    "max_duration_seconds": 360,
}

#: 可灵文生音效。文档:https://kling.ai/document-api/api/video/audio-generation/text-to-audio(2026-09-25 核)。
#: 提示词 ≤200 字必填;时长 3.0–10.0 秒必填(接口收一位小数,这里只放整数 —— 整数是它的子集)。
KLING_TEXT_TO_AUDIO_CAPABILITIES = {
    "modes": ["text-to-sfx"],
    "parameter_keys": ["duration_seconds"],
    "duration_seconds": [],
    "min_duration_seconds": 3,
    "max_duration_seconds": 10,
    "default_duration_seconds": 5,
    "max_prompt_chars": 200,
}

#: 可灵视频生音效。文档:https://kling.ai/document-api/api/video/audio-generation/video-to-audio(2026-09-25 核)。
#: 输入视频 mp4/mov、≤100MB、3–20 秒,**只收链接**(或可灵自己生成的视频 id);提示词(音效)和
#: `bgm_prompt`(配乐)各 ≤200 字、都可以不给。接口同时交回配好声的视频和单独的音轨 —— 这是音频
#: 生成,我们取音轨。
KLING_VIDEO_TO_AUDIO_CAPABILITIES = {
    "modes": ["video-to-audio"],
    "parameter_keys": ["source_video", "bgm_prompt", "asmr_mode"],
    "boolean_parameters": ["asmr_mode"],
    "default_asmr_mode": False,
    "source_limits": {"source_video": 1},
    "requires_source": [["source_video"]],
    "url_only_roles": ["source_video"],
    "prompt": "optional",
    "max_prompt_chars": 200,
    "parameter_schema": {"bgm_prompt": {"type": "string", "title": "BGM prompt"}},
}

#: 火山引擎 AI 音乐生成(人声歌曲)。文档:https://www.volcengine.com/docs/84992/2091679(2026-07-24 更新,
#: 2026-09-25 核)。时长 30–240 秒;歌词 / 描述 5–700 汉字或 5–2000 英文字符;v4.x 上两者只能给一个、
#: 同时给以歌词为准 —— 所以两段都给时当场拦(`lyrics_excludes_prompt`)。v5.0 是文档说的下一个默认版本。
VOLCANO_SONG_CAPABILITIES = {
    "modes": ["lyrics-to-song", "text-to-music"],
    "parameter_keys": ["lyrics", "duration_seconds", "model_version"],
    "duration_seconds": [],
    "min_duration_seconds": 30,
    "max_duration_seconds": 240,
    "max_prompt_chars": 2000,
    "max_lyrics_chars": 2000,
    "lyrics_excludes_prompt": True,
    "parameter_choices": {"model_version": ["v5.0", "v4.3", "v4.0"]},
    "default_model_version": "v5.0",
}

#: 火山引擎 AI 音乐生成(纯音乐 / BGM)。文档:https://www.volcengine.com/docs/84992/2100970(2026-07-24 更新)。
#: 描述(`Text`)**只收中文**;v5.0 时长 30–120 秒(价目页写的是「60s 以内」,两页不一致,按接口页)。
VOLCANO_BGM_CAPABILITIES = {
    "modes": ["text-to-bgm"],
    "parameter_keys": ["duration_seconds"],
    "duration_seconds": [],
    "min_duration_seconds": 30,
    "max_duration_seconds": 120,
}

#: Google Lyria 3 / 3.5(Gemini API generateContent)。文档:https://ai.google.dev/gemini-api/docs/generate-content/music-generation
#: 与 https://ai.google.dev/gemini-api/docs/models/lyria-3.5(2026-09-25 核)。**没有结构化参数**:
#: 纯音乐、歌词都按文档的写法拼进提示词(见 adapters/google/lyria)。可以附最多 10 张图(图生音乐)。
GOOGLE_LYRIA_CAPABILITIES = {
    "modes": ["text-to-music", "lyrics-to-song", "text-to-bgm", "image-to-music"],
    "parameter_keys": ["lyrics", "instrumental", "reference_image"],
    "boolean_parameters": ["instrumental"],
    "default_instrumental": False,
    "source_limits": {"reference_image": 10},
}

#: 百炼 Fun-Music。文档:https://help.aliyun.com/zh/model-studio/fun-music-api(2026-09-25 核)。**仅北京地域、
#: 需要先在模型广场申请**。v1:描述和歌词至少一段;同时给时歌词覆盖描述(文档原话),所以两段都给时当场拦。
#: 歌词 5–350 汉字或 5–2000 英文字符 —— 上限取 2000,不把长英文歌词挡在门外;中文超 350 字由接口拒。
ALIBABA_FUN_MUSIC_CAPABILITIES = {
    "modes": ["text-to-music", "lyrics-to-song", "text-to-bgm"],
    "parameter_keys": ["lyrics", "instrumental", "vocal_gender", "output_format"],
    "boolean_parameters": ["instrumental"],
    "default_instrumental": False,
    "max_prompt_chars": 2000,
    "max_lyrics_chars": 2000,
    "lyrics_excludes_prompt": True,
    "parameter_schema": {"vocal_gender": VOCAL_GENDER_SCHEMA},
    "parameter_choices": {"output_format": ["mp3", "wav"]},
    "default_output_format": "mp3",
}
#: preview:描述必填、没有性别;歌词会覆盖必填的描述 —— 这一对在它身上说不通,所以不开放歌词。
ALIBABA_FUN_MUSIC_PREVIEW_CAPABILITIES = {
    "modes": ["text-to-music", "text-to-bgm"],
    "parameter_keys": ["instrumental", "output_format"],
    "boolean_parameters": ["instrumental"],
    "default_instrumental": False,
    "max_prompt_chars": 2000,
    "parameter_choices": {"output_format": ["mp3", "wav"]},
    "default_output_format": "mp3",
}

#: 百炼 qwen-audio-3.1-tts-next(文档称 AudioGen:语音、音效、环境声一个模型)。文档:
#: https://www.alibabacloud.com/help/en/model-studio/audio-generation-api(2026-09-25 核)。仅北京地域。
#: 描述 ≤3000 字;最多 3 段参考音频(每段 ≤30 秒、≤10MB),提示词里用 @voice1..@voice3 指它们;
#: 一次最多出 120 秒,**没有时长参数**。
ALIBABA_AUDIOGEN_CAPABILITIES = {
    "modes": ["text-to-sfx", "text-to-audio"],
    "parameter_keys": ["reference_audio", "seed", "output_format"],
    "source_limits": {"reference_audio": 3},
    "max_prompt_chars": 3000,
    "parameter_choices": {"output_format": ["wav", "mp3"]},
    "default_output_format": "wav",
}

#: 原厂音频模型:(vendor, model, 描述符)。和 Evolink 那张表同一个形状,一行一个模型。
AUDIO_BUILTIN_MODELS = [
    ("google", "lyria-3.5", GOOGLE_LYRIA_CAPABILITIES),
    ("google", "lyria-3-pro-preview", GOOGLE_LYRIA_CAPABILITIES),
    ("google", "lyria-3-clip-preview", GOOGLE_LYRIA_CAPABILITIES),
    # 可灵的两个音频接口**没有模型字段**,路径就是能力;这两个 id 是我们给这两条路起的名字
    # (和视频那边的 `kling` 一样),Adapter 按它选路径。
    ("kuaishou", "kling-text-to-audio", KLING_TEXT_TO_AUDIO_CAPABILITIES),
    ("kuaishou", "kling-video-to-audio", KLING_VIDEO_TO_AUDIO_CAPABILITIES),
    # 火山的模型 id 就是接口的 Action 名:*ForTime 是按秒后付费,另两个是预付费资源包 —— 账号开的是
    # 哪一种就用哪一个,开错了接口会回 APINoSource。
    ("volcano-music", "GenSongForTime", VOLCANO_SONG_CAPABILITIES),
    ("volcano-music", "GenBGMForTime", VOLCANO_BGM_CAPABILITIES),
    ("volcano-music", "GenSongV4", VOLCANO_SONG_CAPABILITIES),
    ("volcano-music", "GenBGM", VOLCANO_BGM_CAPABILITIES),
    ("alibaba", "fun-music-v1", ALIBABA_FUN_MUSIC_CAPABILITIES),
    ("alibaba", "fun-music-preview", ALIBABA_FUN_MUSIC_PREVIEW_CAPABILITIES),
    ("alibaba", "qwen-audio-3.1-tts-next", ALIBABA_AUDIOGEN_CAPABILITIES),
]

EVOLINK_BUILTIN_MODELS = [
    # Seedance 经 Evolink 是一条独立于火山方舟的路由；不在本地做「真人」关键词拦截，
    # 实际审核仍由 Evolink 当前选中的上游型号决定。
    ("seedance-1.5-pro", "video", EVOLINK_SEEDANCE_15_CAPABILITIES),
    # Seedance 2.5 的五种模式是五个模型 id(见上方 EVOLINK_SEEDANCE_25_* 的注释)。
    ("seedance-2.5-text-to-video", "video", EVOLINK_SEEDANCE_25_T2V_CAPABILITIES),
    ("seedance-2.5-image-to-video", "video", EVOLINK_SEEDANCE_25_I2V_CAPABILITIES),
    ("seedance-2.5-reference-to-video", "video", EVOLINK_SEEDANCE_25_R2V_CAPABILITIES),
    ("seedance-2.5-video-edit", "video", EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES),
    ("seedance-2.5-video-extend", "video", EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES),
    # Seedance 2.0 标准 / Fast 各自拆成文生、图生（含首尾帧）、全能参考三条模型 id。
    ("seedance-2.0-text-to-video", "video", EVOLINK_SEEDANCE_20_T2V_CAPABILITIES),
    ("seedance-2.0-image-to-video", "video", EVOLINK_SEEDANCE_20_I2V_CAPABILITIES),
    ("seedance-2.0-reference-to-video", "video", EVOLINK_SEEDANCE_20_R2V_CAPABILITIES),
    ("seedance-2.0-fast-text-to-video", "video", EVOLINK_SEEDANCE_20_FAST_T2V_CAPABILITIES),
    ("seedance-2.0-fast-image-to-video", "video", EVOLINK_SEEDANCE_20_FAST_I2V_CAPABILITIES),
    ("seedance-2.0-fast-reference-to-video", "video", EVOLINK_SEEDANCE_20_FAST_R2V_CAPABILITIES),
    ("sora-2-preview", "video", EVOLINK_VIDEO_I2V_CAPABILITIES),
    ("kling-o3-text-to-video", "video", EVOLINK_VIDEO_T2V_CAPABILITIES),
    ("kling-o3-image-to-video", "video", EVOLINK_VIDEO_I2V_CAPABILITIES),
    ("veo-3.1-generate-preview", "video", EVOLINK_VIDEO_T2V_CAPABILITIES),
    ("MiniMax-Hailuo-2.3", "video", EVOLINK_VIDEO_T2V_CAPABILITIES),
    ("wan2.6-text-to-video", "video", EVOLINK_VIDEO_T2V_CAPABILITIES),
    ("wan2.6-image-to-video", "video", EVOLINK_VIDEO_I2V_CAPABILITIES),
    ("grok-imagine-text-to-video", "video", EVOLINK_VIDEO_T2V_CAPABILITIES),
    ("grok-imagine-image-to-video", "video", EVOLINK_VIDEO_I2V_CAPABILITIES),
    ("veo3.1-pro", "video", EVOLINK_VEO_31_PRO_CAPABILITIES),
    ("gpt-image-1.5", "image", EVOLINK_IMAGE_EDIT_CAPABILITIES),
    ("gemini-3.1-flash-image-preview", "image", EVOLINK_IMAGE_EDIT_CAPABILITIES),
    ("z-image-turbo", "image", EVOLINK_IMAGE_CAPABILITIES),
    ("doubao-seedream-4.5", "image", EVOLINK_IMAGE_CAPABILITIES),
    ("qwen-image-edit", "image", EVOLINK_IMAGE_EDIT_CAPABILITIES),
    ("wan2.5-text-to-image", "image", EVOLINK_IMAGE_CAPABILITIES),
    ("wan2.5-image-to-image", "image", EVOLINK_IMAGE_EDIT_CAPABILITIES),
    ("suno-v5.5-beta", "audio", EVOLINK_SUNO_V55_CAPABILITIES),
    ("suno-v5-beta", "audio", EVOLINK_SUNO_CAPABILITIES),
    ("suno-v4.5plus-beta", "audio", EVOLINK_SUNO_CAPABILITIES),
    ("suno-v4.5all-beta", "audio", EVOLINK_SUNO_CAPABILITIES),
    ("suno-v4.5-beta", "audio", EVOLINK_SUNO_CAPABILITIES),
    ("suno-v4-beta", "audio", EVOLINK_SUNO_V4_CAPABILITIES),
]

BUILTIN_MODELS = [
    *[
        {
            "id": f"{vendor}:{model}:audio",
            "provider": vendor,
            "kind": "audio",
            "model": model,
            "capabilities": capabilities,
        }
        for vendor, model, capabilities in AUDIO_BUILTIN_MODELS
    ],
    *[
        {
            "id": f"evolink:{model}:{kind}",
            "provider": "evolink",
            "kind": kind,
            "model": model,
            "capabilities": capabilities,
        }
        for model, kind, capabilities in EVOLINK_BUILTIN_MODELS
    ],
    {
        "id": "minimax:MiniMax-H3:video",
        "provider": "minimax",
        "kind": "video",
        "model": "MiniMax-H3",
        "capabilities": MINIMAX_VIDEO_CAPABILITIES,
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
        "capabilities": GOOGLE_VEO_VIDEO_CAPABILITIES,
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
        "capabilities": KLING_V3_OMNI_VIDEO_CAPABILITIES,
    },
    {
        "id": "kuaishou:kling-3.0-turbo:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling-3.0-turbo",
        "capabilities": KLING_V3_VIDEO_CAPABILITIES,
    },
]

#: **能力档案的名册。** 上面那几十个常量本来就是"档案" —— 9 份被 28 行共用,只是没有名字,
#: 于是"另一条通道也有这个模型"每出现一次就只能再抄一行(openai / openai-compatible 下的
#: gpt-image-2 就是抄出来的一对)。给它们一个稳定的 id 之后,这件事有了第二种说法:
#: 用户在自己那行模型上指一份档案,而不是等我们补一行。
#:
#: id 由常量名推出来(`OPENAI_IMAGE_CAPABILITIES` → `openai-image`),但**写成显式的一行**:
#: 它会被存进用户的数据里,不能因为有人重命名了常量就悄悄变。改名要在这里同步改,并且
#: 想清楚存量数据怎么办。
CAPABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "openai-image": OPENAI_IMAGE_CAPABILITIES,
    "qwen-text-image": QWEN_TEXT_IMAGE_CAPABILITIES,
    "qwen-pro-image": QWEN_PRO_IMAGE_CAPABILITIES,
    "qwen-edit-image": QWEN_EDIT_IMAGE_CAPABILITIES,
    "seedream-4-image": SEEDREAM_4_IMAGE_CAPABILITIES,
    "seedream-3-image": SEEDREAM_3_IMAGE_CAPABILITIES,
    "wan-video": WAN_VIDEO_CAPABILITIES,
    "wan-27-t2v": WAN_27_T2V_CAPABILITIES,
    "wan-27-i2v": WAN_27_I2V_CAPABILITIES,
    "wan-27-r2v": WAN_27_R2V_CAPABILITIES,
    "kling-legacy-video": KLING_LEGACY_VIDEO_CAPABILITIES,
    "kling-v3-video": KLING_V3_VIDEO_CAPABILITIES,
    "kling-v3-omni-video": KLING_V3_OMNI_VIDEO_CAPABILITIES,
    "wan-video-edit": WAN_VIDEO_EDIT_CAPABILITIES,
    "seedance-2-video": SEEDANCE_2_VIDEO_CAPABILITIES,
    "seedance-2-small-video": SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
    "seedance-1-video": SEEDANCE_1_VIDEO_CAPABILITIES,
    "seedance-15-video": SEEDANCE_15_VIDEO_CAPABILITIES,
    "minimax-video": MINIMAX_VIDEO_CAPABILITIES,
    "evolink-video-t2v": EVOLINK_VIDEO_T2V_CAPABILITIES,
    "evolink-video-i2v": EVOLINK_VIDEO_I2V_CAPABILITIES,
    "evolink-seedance-15": EVOLINK_SEEDANCE_15_CAPABILITIES,
    "evolink-seedance-20-t2v": EVOLINK_SEEDANCE_20_T2V_CAPABILITIES,
    "evolink-seedance-20-i2v": EVOLINK_SEEDANCE_20_I2V_CAPABILITIES,
    "evolink-seedance-20-r2v": EVOLINK_SEEDANCE_20_R2V_CAPABILITIES,
    "evolink-seedance-20-fast-t2v": EVOLINK_SEEDANCE_20_FAST_T2V_CAPABILITIES,
    "evolink-seedance-20-fast-i2v": EVOLINK_SEEDANCE_20_FAST_I2V_CAPABILITIES,
    "evolink-seedance-20-fast-r2v": EVOLINK_SEEDANCE_20_FAST_R2V_CAPABILITIES,
    "evolink-seedance-25-t2v": EVOLINK_SEEDANCE_25_T2V_CAPABILITIES,
    "evolink-seedance-25-i2v": EVOLINK_SEEDANCE_25_I2V_CAPABILITIES,
    "evolink-seedance-25-r2v": EVOLINK_SEEDANCE_25_R2V_CAPABILITIES,
    "evolink-seedance-25-video-edit": EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES,
    "evolink-seedance-25-video-extend": EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES,
    "evolink-image": EVOLINK_IMAGE_CAPABILITIES,
    "evolink-image-edit": EVOLINK_IMAGE_EDIT_CAPABILITIES,
    "evolink-veo-31-pro": EVOLINK_VEO_31_PRO_CAPABILITIES,
    "google-veo-video": GOOGLE_VEO_VIDEO_CAPABILITIES,
    "evolink-suno": EVOLINK_SUNO_CAPABILITIES,
    "evolink-suno-v4": EVOLINK_SUNO_V4_CAPABILITIES,
    "evolink-suno-v55": EVOLINK_SUNO_V55_CAPABILITIES,
    "kling-text-to-audio": KLING_TEXT_TO_AUDIO_CAPABILITIES,
    "kling-video-to-audio": KLING_VIDEO_TO_AUDIO_CAPABILITIES,
    "volcano-song": VOLCANO_SONG_CAPABILITIES,
    "volcano-bgm": VOLCANO_BGM_CAPABILITIES,
    "google-lyria": GOOGLE_LYRIA_CAPABILITIES,
    "alibaba-fun-music": ALIBABA_FUN_MUSIC_CAPABILITIES,
    "alibaba-fun-music-preview": ALIBABA_FUN_MUSIC_PREVIEW_CAPABILITIES,
    "alibaba-audiogen": ALIBABA_AUDIOGEN_CAPABILITIES,
}

#: 按对象身份反查档案 id。**不比较内容** —— 两份内容恰好相同的档案仍是两份(它们会各自演化)。
_PROFILE_ID_BY_IDENTITY: dict[int, str] = {id(caps): name for name, caps in CAPABILITY_PROFILES.items()}


def profile_id_for(vendor: str, model: str, kind: str) -> str | None:
    """这条内置记录用的是哪份档案。查不到这个模型时回 None。"""
    for item in BUILTIN_MODELS:
        if item["provider"] == vendor and item["model"] == model and item["kind"] == kind:
            return _PROFILE_ID_BY_IDENTITY.get(id(item["capabilities"]))
    return None


#: 某个 vendor 在某种生成能力下的**兜底**描述符。目录里没登记的模型(私有部署、别名、
#: 用户手填的)照样要能出现在选择器里并给出一组可用参数 —— 缺描述符不该等于"不能用"。
_FALLBACK_BY_KIND: dict[str, dict[str, Any]] = {
    "image": {
        "modes": ["text-to-image"],
        "parameter_keys": [],
    },
    "video": {
        "modes": ["text-to-video"],
        "parameter_keys": [],
    },
    "audio": {
        "modes": ["text-to-audio"],
        "parameter_keys": [],
    },
}


def resolve_capability_ref(
    ref: str | None, kind: str, *, custom: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """用户在自己那行模型上写下的「生成参数按什么来」。认不出就回 None(**不猜**)。

    两种写法:

      `model:<provider>/<model>`  「它和 X 一样」。存的是指针不是快照 —— 以后我们把 X 的描述符
                                  改宽了,指着它的那些行**跟着变**。用户写 `gpt-image-2-client`
                                  时想说的正是这个:它就是 gpt-image-2,别的我不管。
      `profile:<id>`              目录里没有对应模型时,直接指一份能力档案(见 CAPABILITY_PROFILES)。

    指向的东西不存在时回 None 而不是抛:一个指向已被删掉的模型的旧值,不该让整个模型列表 500。
    界面那边会因此显示成"还没认出来",用户重新指一次即可。
    """
    text = (ref or "").strip()
    if not text:
        return None
    prefix, _, rest = text.partition(":")
    if prefix == "profile":
        name = rest.strip()
        #: 自定义的排在前面:同名时用户的那份说了算 —— 内置 id 是 `openai-image` 这种词,
        #: 自定义的是 32 位十六进制,实际撞不上,但顺序仍要写明白。
        found = (custom or {}).get(name) or CAPABILITY_PROFILES.get(name)
        return dict(found) if found is not None else None
    if prefix == "model":
        target_vendor, _, target_model = rest.partition("/")
        #: 跨 kind 不认:同一个 id 的图片档案套到视频上,参数是另一套。
        return known_capabilities_for(target_vendor.strip(), target_model.strip(), kind)
    return None


def capabilities_for(
    vendor: str,
    model: str,
    kind: str,
    *,
    ref: str | None = None,
    custom: dict[str, dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """某个模型在某种生成能力下的参数描述符(尺寸/时长/支持哪些参数)。

    **这是关于供应商 API 的静态知识,不是用户配置** —— 所以它是一张查表,不再是数据库里的行。
    以前每条描述符都在 `generation_models` 里占一行,于是"有哪些模型可选"这件事有了第二个
    答案:设置页看 provider_models,生成页看 generation_models,两边永远对不齐(有的模型只在
    后者里,设置页加的进不了前者)。

    只精确匹配 (provider, model, kind)。查不到时**不猜这个模型** —— 同一个供应商下,同系列
    不同型号的时长、素材角色和枚举值经常不同,继承目录第一项会让界面主动发送用户没有选择、
    目标模型也未必支持的参数。

    但"不猜模型"不等于"什么都不知道"。请求是**我们自己构造的**,所以 Adapter 说得出它能发
    哪几项标量参数。那个面与模型名无关时(`surface_depends_on_model = False`),兜底就用它 ——
    只给**键**,不声称任何取值范围。这不是推测:代码就在那儿,发哪几项一目了然。
    此前这里返回的是空集,于是一个中转上的模型看起来像"它就是没有参数",而那段代码早就知道
    自己准备发哪七项(见 ADR 0015)。
    """
    chosen = resolve_capability_ref(ref, kind, custom=custom)
    if chosen is not None:
        return chosen
    # **连接自己说的**(插件生成供应商在目录里声明的,见 ADR 0020)排在内置目录前面:
    # 那是 Adapter —— 这里就是插件 —— 对它自己要发的请求的描述,正是 ADR 0015 的「参数面由
    # Adapter 说」。内置目录里本来也没有它们。
    if declared:
        return dict(declared)
    exact = known_capabilities_for(vendor, model, kind)
    if exact is not None:
        return exact
    return fallback_capabilities(vendor, kind)


def adapter_parameter_surface(vendor: str, kind: str) -> tuple[str, ...]:
    """这条通道能发出去的标量参数;依赖模型名的一律回空(保守)。"""
    from app.ai.providers import get_generation_adapter

    adapter = get_generation_adapter(vendor, kind)
    if adapter is None or adapter.surface_depends_on_model:
        return ()
    return tuple(adapter.parameter_surface)


def fallback_capabilities(vendor: str, kind: str) -> dict[str, Any]:
    """目录不认识这个模型时给什么。

    **键来自 Adapter,取值范围一个都不声称。** 请求是我们自己构造的,发哪几项是知道的;
    这个模型收哪些**取值**才是未知的。界面据此渲染成自由输入 —— 摆出来,但在用户填之前
    不带任何值(见 ADR 0015 与 lib/generationCapabilities 的 UNDECLARED / DURATION_UNSET)。

    **这一步曾经放不出来。** 界面那一层原本有自己的造值逻辑:一个参数键只要出现、清单缺席,
    就凭空造出 size→["1024x1024"]、resolution→["720p"]、aspect_ratio→["16:9"]、duration→5
    并取第一项提交。于是"知道能发哪几项"会变成"声称这个模型是 720p / 16:9 / 5 秒",而用户
    一项都没选过 —— 那时这里的空是**承重**的,是唯一拦住它的闸。
    `tests/test_generation_capability_contract.py` 的 `不伪造第一款型号的参数` 抓的正是这个。
    界面改成"不知道就空着"之后,这道闸才拆得掉。
    """
    base = dict(_FALLBACK_BY_KIND.get(kind, {}))
    surface = adapter_parameter_surface(vendor, kind)
    if surface:
        base["parameter_keys"] = list(surface)
    return base


def capabilities_are_known(
    vendor: str,
    model: str,
    kind: str,
    *,
    ref: str | None = None,
    custom: dict[str, dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
) -> bool:
    """这个模型的参数是**认出来的**,还是落到了兜底。

    界面要分得开这两种零:「这个模型确实没有可调参数」和「我们不认识这个模型」。合成一个的
    后果今天见过 —— 生成节点的「参数」按钮对着一堆其实有参数的模型悄悄消失了。
    """
    return (
        resolve_capability_ref(ref, kind, custom=custom) is not None
        or bool(declared)
        or known_capabilities_for(vendor, model, kind) is not None
    )


def known_capabilities_for(vendor: str, model: str, kind: str) -> dict[str, Any] | None:
    """同上,但**查不到就是 None**,不给兜底。

    兜底那份是给界面用的 —— 总得渲染出点什么。校验不能用它:落到兜底的意思是「我们不认识
    这个模型」(用户自建的、中转上的别名),拿那份窄名单去拦,会挡住本来能用的参数。
    两种需求共用一个返回值时,分不出「它只支持这些」和「我们不知道它支持什么」。
    """
    for item in BUILTIN_MODELS:
        if item["provider"] == vendor and item["model"] == model and item["kind"] == kind:
            return dict(item["capabilities"])
    return None


def builtin_models_for(vendor: str, kind: str) -> list[str]:
    """该 vendor 在该能力下的内置模型名 —— 用户没在设置里加过任何模型时的候选。"""
    return [item["model"] for item in BUILTIN_MODELS if item["provider"] == vendor and item["kind"] == kind]

#: 「能用来生成的 (连接 × 模型) 列表」是 db 感知的,住在 resolution.py 那个集成缝上。
#: 这里保持纯静态目录 —— 叶模块向上伸手会成环(import 分层测试钉着)。
