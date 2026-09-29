"""数字人的能力描述符:说话照片(一张人像跟着驱动音频说话)与对口型(原片的嘴对上新配音)。见 ADR 0028。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

#: 说话照片(ADR 0028):一张人像按驱动音频说话。**成片长度跟着音频走**,不收时长,也不收提示词。
#: 文档原话:音频「文件<15M,时长<20s」;图边长 400–7000;480P(默认)/ 720P。提交前适配器先调
#: `wan2.2-s2v-detect` 预检人像(见 adapters/alibaba/dashscope/digital_human)。
WAN_22_S2V_CAPABILITIES = {
    "modes": ["speech-to-video"],
    "endpoint": "dashscope",
    "prompt": "none",
    "parameter_keys": ["resolution", "first_frame", "driving_audio"],
    "resolutions": ["480P", "720P"],
    "default_resolution": "480P",
    "source_limits": {"first_frame": 1, "driving_audio": 1},
    "requires_source": [["first_frame"], ["driving_audio"]],
    "duration_follows": "driving_audio",
    "source_duration_seconds": {"driving_audio": [1, 20]},
}

#: 火山 · 即梦 OmniHuman 1.5 说话照片(ADR 0028 阶段 4):一张图 + 一段音频 → 跟着音频说话的视频,可以加一句
#: 提示词调画面、动作和运镜。素材只收公网链接(`url_only_roles`,漏斗先传到用户的对象存储);音频必须短于 60 秒。
#: 输出 720 / 1080(默认 1080)。文档:https://www.volcengine.com/docs/85621/1829013
VOLCANO_OMNIHUMAN_15_CAPABILITIES = {
    "modes": ["speech-to-video"],
    "prompt": "optional",
    "parameter_keys": ["resolution", "seed", "first_frame", "driving_audio"],
    "resolutions": ["720p", "1080p"],
    "default_resolution": "1080p",
    "source_limits": {"first_frame": 1, "driving_audio": 1},
    "requires_source": [["first_frame"], ["driving_audio"]],
    "url_only_roles": ["first_frame", "driving_audio"],
    "duration_follows": "driving_audio",
    "source_duration_seconds": {"driving_audio": [1, 59]},
}

#: HeyGen 说话照片(ADR 0028 阶段 4,海外):Avatar IV 把任意一张人像跟着配音动起来,可以写一句动作提示词
#: (`motion_prompt`)。本地素材走 HeyGen 自己的直传,所以不要 `url_only_roles`。配音上限文档两处说法不一
#: (30 分钟 / 头像输入 10 分钟),按严的写 600 秒。文档:https://developers.heygen.com/audio-to-video.md
HEYGEN_AVATAR_CAPABILITIES = {
    "modes": ["speech-to-video"],
    "prompt": "optional",
    "parameter_keys": ["resolution", "first_frame", "driving_audio"],
    "resolutions": ["720p", "1080p"],
    "default_resolution": "1080p",
    "source_limits": {"first_frame": 1, "driving_audio": 1},
    "requires_source": [["first_frame"], ["driving_audio"]],
    "duration_follows": "driving_audio",
    "source_duration_seconds": {"driving_audio": [1, 600]},
}

#: HeyGen 对口型:原片的嘴对上新配音(精度模式)。成片长度跟着新配音走(`enable_dynamic_duration` 默认开)。
#: 原片只收 mp4 / webm。文档没写时长上限,只按直传的 200MiB 封顶,描述符不编一个。
#: 文档:https://developers.heygen.com/lipsync-precision.md
HEYGEN_LIPSYNC_CAPABILITIES = {
    "modes": ["video-lipsync"],
    "prompt": "none",
    "parameter_keys": ["source_video", "driving_audio"],
    "source_limits": {"source_video": 1, "driving_audio": 1},
    "requires_source": [["source_video"], ["driving_audio"]],
    "duration_follows": "driving_audio",
}

#: Hedra Character-3 说话照片(ADR 0028 阶段 4,海外):一张图 + 一段配音(0.5–600 秒,描述符按整秒写 1–600)。
#: 提示词接口要求必填,没写就由适配器给一句中性的;画幅按原图挑最接近的一档。图和音频先传到 Hedra 自己的
#: 临时存储(它只认自己发的链接),不用对象存储。
#: 文档:https://www.hedra.com/docs/api-reference/v3/run-a-model/run-hedra-character-3-hedra-character-3.md
HEDRA_CHARACTER_3_CAPABILITIES = {
    "modes": ["speech-to-video"],
    "prompt": "optional",
    "parameter_keys": ["resolution", "first_frame", "driving_audio"],
    "resolutions": ["540p", "720p", "1080p"],
    "default_resolution": "720p",
    "source_limits": {"first_frame": 1, "driving_audio": 1},
    "requires_source": [["first_frame"], ["driving_audio"]],
    "duration_follows": "driving_audio",
    "source_duration_seconds": {"driving_audio": [1, 600]},
}

#: 改口型(ADR 0028):一段已有视频的嘴对上新的音频;可选一张参考人像指定改哪张脸。视频、音频都是 2–120 秒;
#: 音频比视频长时适配器开 `video_extension`,用正放倒放交替把视频补齐。不收提示词。
VIDEORETALK_CAPABILITIES = {
    "modes": ["video-lipsync"],
    "endpoint": "dashscope",
    "prompt": "none",
    "parameter_keys": ["source_video", "driving_audio", "reference_image"],
    "source_limits": {"source_video": 1, "driving_audio": 1, "reference_image": 1},
    "requires_source": [["source_video"], ["driving_audio"]],
    "duration_follows": "driving_audio",
    "source_duration_seconds": {"source_video": [2, 120], "driving_audio": [2, 120]},
}

#: 可灵数字人(ADR 0028 阶段 4):一张人像 + 一段配音 → 说话视频。图片、音频都能直接传(Base64),不必先换直链;
#: 配音 2–300 秒;提示词可写动作、情绪、运镜(≤2500 字)。清晰度照可灵旧接口的规矩:1080p 走 pro(画质更好、更贵)。
#: 文档:https://kling.ai/document-api/api/video/avatar(2026-09-28 读)。
KLING_AVATAR_CAPABILITIES = {
    "modes": ["speech-to-video"],
    "prompt": "optional",
    "max_prompt_chars": 2500,
    "parameter_keys": ["resolution", "first_frame", "driving_audio"],
    "resolutions": ["720p", "1080p"],
    "default_resolution": "720p",
    "source_limits": {"first_frame": 1, "driving_audio": 1},
    "requires_source": [["first_frame"], ["driving_audio"]],
    "duration_follows": "driving_audio",
    "source_duration_seconds": {"driving_audio": [2, 300]},
}

#: 可灵对口型:原片里出现最久的那张脸,嘴对上新的一段配音。**先认人脸再对口型**两步由适配器做;认人脸那一步
#: 只收视频链接(本地原片由生成漏斗先换成直链)。原片 2–60 秒、720p / 1080p;配音 2–60 秒。出片和原片一样长。
#: 文档:https://kling.ai/document-api/api/video/lip-sync(2026-09-28 读)。
KLING_LIPSYNC_CAPABILITIES = {
    "modes": ["video-lipsync"],
    "prompt": "none",
    "parameter_keys": ["source_video", "driving_audio"],
    "source_limits": {"source_video": 1, "driving_audio": 1},
    "requires_source": [["source_video"], ["driving_audio"]],
    "url_only_roles": ["source_video"],
    "duration_follows": "source_video",
    "source_duration_seconds": {"source_video": [2, 60], "driving_audio": [2, 60]},
}
