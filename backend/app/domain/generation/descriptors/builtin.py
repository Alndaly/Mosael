"""内置模型名册:哪家、哪个模型 id、哪种生成,用的是哪份描述符。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

from app.domain.generation.descriptors.image import (
    EVOLINK_IMAGE_CAPABILITIES,
    EVOLINK_IMAGE_EDIT_CAPABILITIES,
    OPENAI_IMAGE_CAPABILITIES,
    QWEN_EDIT_IMAGE_CAPABILITIES,
    QWEN_PRO_IMAGE_CAPABILITIES,
    QWEN_TEXT_IMAGE_CAPABILITIES,
    SEEDREAM_3_IMAGE_CAPABILITIES,
    SEEDREAM_4_IMAGE_CAPABILITIES,
)
from app.domain.generation.descriptors.avatar import (
    HEDRA_CHARACTER_3_CAPABILITIES,
    HEYGEN_AVATAR_CAPABILITIES,
    HEYGEN_LIPSYNC_CAPABILITIES,
    KLING_AVATAR_CAPABILITIES,
    KLING_LIPSYNC_CAPABILITIES,
    VIDEORETALK_CAPABILITIES,
    VOLCANO_OMNIHUMAN_15_CAPABILITIES,
    WAN_22_S2V_CAPABILITIES,
)
from app.domain.generation.descriptors.video import (
    GOOGLE_VEO_VIDEO_CAPABILITIES,
    KLING_LEGACY_VIDEO_CAPABILITIES,
    KLING_V3_OMNI_VIDEO_CAPABILITIES,
    KLING_V3_VIDEO_CAPABILITIES,
    MINIMAX_VIDEO_CAPABILITIES,
    SEEDANCE_15_VIDEO_CAPABILITIES,
    SEEDANCE_1_VIDEO_CAPABILITIES,
    SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
    SEEDANCE_2_VIDEO_CAPABILITIES,
    WAN_27_I2V_CAPABILITIES,
    WAN_27_R2V_CAPABILITIES,
    WAN_27_T2V_CAPABILITIES,
    WAN_VIDEO_CAPABILITIES,
    WAN_VIDEO_EDIT_CAPABILITIES,
)
from app.domain.generation.descriptors.evolink_video import (
    EVOLINK_SEEDANCE_15_CAPABILITIES,
    EVOLINK_SEEDANCE_20_FAST_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_FAST_R2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_FAST_T2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_R2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_T2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_R2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_T2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES,
    EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES,
    EVOLINK_VEO_31_PRO_CAPABILITIES,
    EVOLINK_VIDEO_I2V_CAPABILITIES,
    EVOLINK_VIDEO_T2V_CAPABILITIES,
)
from app.domain.generation.descriptors.audio import (
    ALIBABA_AUDIOGEN_CAPABILITIES,
    ALIBABA_FUN_MUSIC_CAPABILITIES,
    ALIBABA_FUN_MUSIC_PREVIEW_CAPABILITIES,
    EVOLINK_SUNO_CAPABILITIES,
    EVOLINK_SUNO_V4_CAPABILITIES,
    EVOLINK_SUNO_V55_CAPABILITIES,
    GOOGLE_LYRIA_CAPABILITIES,
    KLING_TEXT_TO_AUDIO_CAPABILITIES,
    KLING_VIDEO_TO_AUDIO_CAPABILITIES,
    VOLCANO_BGM_CAPABILITIES,
    VOLCANO_SONG_CAPABILITIES,
)

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
    # Seedance 2.5 的五种模式是五个模型 id(见 descriptors/evolink_video 里 EVOLINK_SEEDANCE_25_* 的注释)。
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
        # 说话照片:一张人像按一段话说话(数字人,ADR 0028)。
        "id": "alibaba:wan2.2-s2v:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "wan2.2-s2v",
        "capabilities": WAN_22_S2V_CAPABILITIES,
    },
    {
        # 说话照片:火山 · 即梦 OmniHuman 1.5(数字人,ADR 0028 阶段 4)。走账号级 AK/SK 的「即梦 AI」连接。
        "id": "volcano-visual:omnihuman-1.5:video",
        "provider": "volcano-visual",
        "kind": "video",
        "model": "omnihuman-1.5",
        "capabilities": VOLCANO_OMNIHUMAN_15_CAPABILITIES,
    },
    {
        # 说话照片 / 对口型:HeyGen(海外数字人,ADR 0028 阶段 4)。
        "id": "heygen:heygen-avatar-iv:video",
        "provider": "heygen",
        "kind": "video",
        "model": "heygen-avatar-iv",
        "capabilities": HEYGEN_AVATAR_CAPABILITIES,
    },
    {
        "id": "heygen:heygen-lipsync:video",
        "provider": "heygen",
        "kind": "video",
        "model": "heygen-lipsync",
        "capabilities": HEYGEN_LIPSYNC_CAPABILITIES,
    },
    {
        # 说话照片:Hedra Character-3(海外数字人,ADR 0028 阶段 4)。
        "id": "hedra:hedra-character-3:video",
        "provider": "hedra",
        "kind": "video",
        "model": "hedra-character-3",
        "capabilities": HEDRA_CHARACTER_3_CAPABILITIES,
    },
    {
        # 改口型:一段已有视频的嘴对上新的一段话(数字人,ADR 0028)。
        "id": "alibaba:videoretalk:video",
        "provider": "alibaba",
        "kind": "video",
        "model": "videoretalk",
        "capabilities": VIDEORETALK_CAPABILITIES,
    },
    {
        # 说话照片:可灵数字人。和可灵视频同一个连接(AccessKey + SecretKey)。
        "id": "kuaishou:kling-avatar:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling-avatar",
        "capabilities": KLING_AVATAR_CAPABILITIES,
    },
    {
        # 改口型:可灵对口型(先认人脸,再对口型)。
        "id": "kuaishou:kling-lipsync:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling-lipsync",
        "capabilities": KLING_LIPSYNC_CAPABILITIES,
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
