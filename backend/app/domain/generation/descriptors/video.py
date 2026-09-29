"""视频生成的能力描述符:万相、可灵、方舟 Seedance、MiniMax、Google Veo 这些原厂直连的。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

from app.domain.generation.descriptors.shared import KEYFRAME_GROUP, REFERENCE_GROUP, REFERENCE_SCENE_LIMITS

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
    #: 驱动音频(ADR 0028):文档写音频 2–30 秒;比所选时长长的部分**自动截掉**、成片不跟着音频走 ——
    #: 界面在所选时长短于音频时提醒「后 N 秒会被截掉」。
    "source_duration_seconds": {"driving_audio": [2, 30]},
    "truncates_role": "driving_audio",
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
#: 这一步由适配器代劳(见 ai/providers/adapters/kuaishou/kling/elements):界面上照旧是挂参考图,
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
    #: 参考图不是「这次用几张图」,而是**先建主体再引用**:一组图建一个主体,一次最多引 3 个
    #: (文档原话「最多支持指定 3 个主体」,见 kling/elements.MAX_ELEMENTS_PER_TASK)。分组由
    #: `@资产` 给(每个资产一组,见 domain/entities/mentions);手挂的参考图算一组。
    "reference_subjects": {"max_subjects": 3},
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
    # 本地素材怎么变成链接:随应用内置的「对象存储」插件(plugins/bundled/object-storage,火山 TOS /
    # 阿里云 OSS / 腾讯云 COS / S3 选一家),它的 `storage_upload` 传上去之后交回一条**限时直链** —— 签名在
    # 查询串里,桶不必设成公共读(见 generation/public_links)。方舟自己的文档推荐的也是 TOS。
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
    #: 方舟文档:`generate_audio` 默认 true(2.0 与 1.5 pro 支持)。不声明的话画板节点、AI 工作室当它「关」,
    #: 出来的全是静音片 —— 和直接调接口的结果不一样。
    "default_generate_audio": True,
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
    # 默认值 —— 有首帧时我们根本不传 ratio,交给模型按图片适配(见 providers/adapters/bytedance/ark/video)。
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
    "default_generate_audio": True,
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
