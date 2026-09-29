"""音频生成(音乐 / BGM / 歌曲 / 音效 / 给视频配声)的能力描述符。

由 domain/generation/catalog 统一重新导出;调用方照旧从 catalog 取,这里只放数据。
"""

from __future__ import annotations

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
# 提示词要不要写是各种生成共用的那一格 `prompt`(见 catalog.py 文件头的 PROMPT_MODES):视频配声是 `optional`。
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
